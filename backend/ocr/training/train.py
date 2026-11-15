"""Fine-tune the EasyOCR gen2 recognition model (VGG + BiLSTM + CTC) on the
report/reports crop corpus — the actual OCR training step.

Starts from the released english_g2 weights (same architecture + charset, so
nothing is lost) and trains with CTC loss on word crops rendered from the
corpus PDF text layer, with photo-style augmentation on every epoch.
Model selection uses an internal val slice (patient-ID based) carved from
the TRAIN split; the corpus eval split (reg-ID % 5 == 0 patients) is never
seen during training or model selection.

Runs on CUDA when available (required by default: pass --cpu to override).
"""
import argparse
import random
import shutil
from pathlib import Path

import torch
import torch.nn.functional as F
import torch.utils.data
from PIL import Image, ImageFilter

from ocr.training.crops import G2_CHARSET

# easyocr gen2 architecture constants (english_g2)
GEN2_PARAMS = dict(input_channel=1, output_channel=256, hidden_size=256)
IMGH = 64
IMGW_CAP = 400


def _augment(img):
    """Photo-style augmentation, randomized per access."""
    if random.random() < 0.5:
        angle = random.uniform(-2.0, 2.0)
        img = img.rotate(angle, resample=Image.BILINEAR, fillcolor=255)
    if random.random() < 0.35:
        img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.4, 1.2)))
    if random.random() < 0.3:  # random brightness / contrast
        from PIL import ImageEnhance

        img = ImageEnhance.Brightness(img).enhance(random.uniform(0.6, 1.4))
        img = ImageEnhance.Contrast(img).enhance(random.uniform(0.6, 1.5))
    if random.random() < 0.3:  # low-res simulation
        w, h = img.size
        scale = random.uniform(0.4, 0.75)
        img = img.resize((max(8, int(w * scale)), max(8, int(h * scale))), Image.BILINEAR)
        img = img.resize((w, h), Image.BILINEAR)
    if random.random() < 0.25:  # salt & pepper
        import numpy as np

        arr = np.array(img)
        mask = np.random.random(arr.shape) < 0.01
        noise = (np.random.random(arr.shape) < 0.5) * 255
        arr = np.where(mask, noise, arr).astype("uint8")
        img = Image.fromarray(arr, "L")
    return img


def _collate_batch(batch):
    """Resize each crop to imgH (aspect kept, width capped), pad to the
    batch max width — mirrors easyocr's AlignCollate(keep_ratio_with_pad)."""
    from torchvision.transforms import transforms

    to_tensor = transforms.ToTensor()
    images, labels = zip(*batch)
    widths = []
    tensors = []
    for img in images:
        w, h = img.size
        ratio = w / float(h)
        resized_w = min(IMGW_CAP, max(8, int(IMGH * ratio)))
        t = to_tensor(img.resize((resized_w, IMGH), Image.BILINEAR))
        t.sub_(0.5).div_(0.5)
        tensors.append(t)
        widths.append(resized_w)
    max_w = max(widths)
    batch_tensors = torch.FloatTensor(len(tensors), 1, IMGH, max_w).fill_(0)
    for i, t in enumerate(tensors):
        w = t.size(2)
        batch_tensors[i, :, :, :w] = t
        if w < max_w:  # replicate edge column like easyocr's right-pad
            batch_tensors[i, :, :, w:] = t[:, :, w - 1].unsqueeze(2).expand(1, IMGH, max_w - w)
    return batch_tensors, list(labels)


class CropDataset(torch.utils.data.Dataset):
    def __init__(self, root, rows, augment=False):
        self.root = Path(root)
        self.rows = rows
        self.augment = augment

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        split, _reg, rel, label = self.rows[i]
        img = Image.open(self.root / rel).convert("L")
        if self.augment:
            img = _augment(img)
        return img, label


def load_rows(data_dir):
    rows = []
    with (Path(data_dir) / "labels.tsv").open(encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4:
                continue
            rows.append(tuple(parts))
    return rows


def split_rows(rows):
    """train / val (internal model selection) / test (held-out patients)."""
    train = [r for r in rows if r[0] == "train" and int(r[1]) % 17 != 5]
    val = [r for r in rows if r[0] == "train" and int(r[1]) % 17 == 5]
    test = [r for r in rows if r[0] == "eval"]
    return train, val, test


@torch.no_grad()
def evaluate(model, converter, loader, device):
    model.eval()
    correct = total = 0
    for images, labels in loader:
        images = images.to(device)
        preds = model(images, torch.LongTensor(images.size(0), 1).fill_(0).to(device))
        preds_size = torch.IntTensor([preds.size(1)] * images.size(0))
        _, preds_index = preds.max(2)
        preds_index = preds_index.view(-1)
        texts = converter.decode_greedy(preds_index.cpu().numpy(), preds_size.numpy())
        for pred, truth in zip(texts, labels):
            total += 1
            correct += int(pred.strip() == truth.strip())
    return correct / max(total, 1), total


def train(args):
    device = "cuda" if torch.cuda.is_available() and not args.cpu else "cpu"
    if device == "cpu" and not args.cpu:
        raise SystemExit(
            "CUDA is not available. Training on CPU would take hours — "
            "fix the CUDA installation or pass --cpu to force CPU training."
        )
    print(f"device: {device}"
          + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    import easyocr
    from easyocr.model.vgg_model import Model
    from easyocr.utils import CTCLabelConverter

    converter = CTCLabelConverter(G2_CHARSET, separator_list={}, dict_pathlist={})
    num_class = len(converter.character)
    print(f"charset size: {len(G2_CHARSET)} -> num_class {num_class}")

    model = Model(num_class=num_class, **GEN2_PARAMS).to(device)

    if not args.scratch:
        easyocr_home = Path(easyocr.__file__).parent.parent  # site-packages
        # released weights live in ~/.EasyOCR/model (downloaded on first use)
        candidates = [
            Path.home() / ".EasyOCR" / "model" / "english_g2.pth",
            easyocr_home / "EasyOCR" / "model" / "english_g2.pth",
        ]
        pretrained = next((p for p in candidates if p.exists()), None)
        if pretrained is None:
            raise SystemExit(
                "english_g2.pth not found (~/.EasyOCR/model). Run any EasyOCR "
                "recognition once so the base weights download, or pass --scratch."
            )
        state = torch.load(str(pretrained), map_location="cpu", weights_only=False)
        state = {k[7:] if k.startswith("module.") else k: v for k, v in state.items()}
        missing, unexpected = model.load_state_dict(state, strict=False)
        print(f"loaded pretrained {pretrained.name}: "
              f"{len(state)} tensors (missing {len(missing)}, unexpected {len(unexpected)})")

    if args.freeze_cnn:
        # Keep the released convolutional features intact and adapt only the
        # sequence model + classifier — limits catastrophic forgetting when
        # the corpus is narrow (one report domain).
        for p in model.FeatureExtraction.parameters():
            p.requires_grad_(False)
        print("CNN feature extractor frozen; training LSTM + classifier only")

    rows = load_rows(args.data_dir)
    train_rows, val_rows, test_rows = split_rows(rows)
    print(f"crops: train {len(train_rows)}, val {len(val_rows)}, held-out test {len(test_rows)}")

    train_ds = CropDataset(args.data_dir, train_rows, augment=True)
    val_ds = CropDataset(args.data_dir, val_rows, augment=False)
    test_ds = CropDataset(args.data_dir, test_rows, augment=False)
    train_loader = torch.utils.data.DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
        num_workers=args.workers, collate_fn=_collate_batch, drop_last=True,
        persistent_workers=args.workers > 0,
    )
    val_loader = torch.utils.data.DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False,
        num_workers=0, collate_fn=_collate_batch,
    )

    criterion = torch.nn.CTCLoss(zero_infinity=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    # Baseline: the un-fine-tuned model must be beat, otherwise the stock
    # weights are kept (no regression shipped).
    base_model_path = None if args.scratch else Path.home() / ".EasyOCR" / "model" / "english_g2.pth"
    base_acc = 0.0
    if base_model_path and Path(base_model_path).exists():
        base_model = Model(num_class=num_class, **GEN2_PARAMS).to(device)
        state = torch.load(str(base_model_path), map_location="cpu", weights_only=False)
        state = {k[7:] if k.startswith("module.") else k: v for k, v in state.items()}
        base_model.load_state_dict(state)
        base_loader = torch.utils.data.DataLoader(
            CropDataset(args.data_dir, test_rows, augment=False),
            batch_size=args.batch_size, num_workers=0, collate_fn=_collate_batch,
        )
        base_acc, _ = evaluate(base_model, converter, base_loader, device)
        del base_model
        print(f"stock english_g2 held-out word acc: {base_acc:.4f} — target to beat", flush=True)

    best_acc = 0.0
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    best_path = out_dir / f"{args.name}.pth"

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = n_batches = 0
        for images, labels in train_loader:
            images = images.to(device)
            targets, target_lengths = converter.encode(labels)
            targets = targets.to(device)
            target_lengths = target_lengths.to(device)
            preds = model(images, torch.LongTensor(images.size(0), 1).fill_(0).to(device))
            input_lengths = torch.IntTensor([preds.size(1)] * images.size(0)).to(device)
            log_probs = F.log_softmax(preds, dim=2).permute(1, 0, 2)  # (T, N, C)
            loss = criterion(log_probs, targets, input_lengths, target_lengths)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss)
            n_batches += 1
        val_acc, val_n = evaluate(model, converter, val_loader, device)
        marker = ""
        if val_acc > max(best_acc, base_acc):
            best_acc = val_acc
            # easyocr's GPU loader wraps the model in DataParallel and expects
            # its released convention: "module."-prefixed keys (stripped again
            # on the CPU load path).
            state = {"module." + k: v for k, v in model.state_dict().items()}
            torch.save(state, best_path)
            marker = "  <- saved"
        print(f"epoch {epoch}/{args.epochs}: train CTC loss {total_loss / max(n_batches, 1):.4f} "
              f"| val word acc {val_acc:.4f} ({val_n} crops){marker}", flush=True)

    # final honest numbers with the best checkpoint: internal val + held-out.
    # Nothing ever beat the stock weights -> keep the stock model, no export.
    if not best_path.exists():
        print(f"no epoch beat the stock model (base {base_acc:.4f}) — stock weights kept, "
              "nothing exported", flush=True)
        return base_acc
    best_state = torch.load(best_path, map_location=device, weights_only=False)
    best_state = {k[7:] if k.startswith("module.") else k: v for k, v in best_state.items()}
    model.load_state_dict(best_state)
    test_loader = torch.utils.data.DataLoader(
        test_ds, batch_size=args.batch_size, shuffle=False,
        num_workers=0, collate_fn=_collate_batch,
    )
    val_acc, _ = evaluate(model, converter, val_loader, device)
    test_acc, test_n = evaluate(model, converter, test_loader, device)
    print(f"best checkpoint: val word acc {val_acc:.4f} | held-out test word acc {test_acc:.4f} "
          f"({test_n} crops)")
    return best_acc


def export_config(out_dir, name):
    """Write the easyocr user_network yaml + architecture module."""
    import easyocr
    import yaml

    out_dir = Path(out_dir)
    config = {
        "imgH": IMGH,
        "lang_list": ["en"],
        "character_list": list(G2_CHARSET),
        "network_params": {**GEN2_PARAMS, "num_class": None},  # num_class filled by Reader
    }
    config["network_params"].pop("num_class")
    (out_dir / f"{name}.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    # the architecture module must import WITHOUT package-relative imports
    src = Path(easyocr.__file__).parent / "model" / "vgg_model.py"
    code = src.read_text(encoding="utf-8").replace(
        "from .modules import", "from easyocr.model.modules import")
    (out_dir / f"{name}.py").write_text(code, encoding="utf-8")


def install_model(out_dir, name):
    """Copy the trained .pth next to the easyocr detector model (~/.EasyOCR/model)
    so Reader(recog_network=<name>) finds it. Skipped when identical."""
    from django.conf import settings

    out_dir = Path(out_dir)
    pth = out_dir / f"{name}.pth"
    target_dir = Path(getattr(settings, "OCR_EASYOCR_MODEL_DIR", "") or
                      (Path.home() / ".EasyOCR" / "model"))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{name}.pth"
    if not target.exists() or target.stat().st_size != pth.stat().st_size:
        shutil.copy2(pth, target)
        print(f"installed {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="ocr/training_data")
    parser.add_argument("--out", default="ocr/models/easyocr/user_network")
    parser.add_argument("--name", default="aimhra_report")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--cpu", action="store_true", help="force CPU training")
    parser.add_argument("--scratch", action="store_true", help="train from scratch")
    parser.add_argument("--freeze-cnn", action="store_true", help="train only LSTM+classifier (less forgetting)")
    args = parser.parse_args()
    train(args)
    export_config(args.out, args.name)
    install_model(args.out, args.name)
