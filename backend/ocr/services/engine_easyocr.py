"""EasyOCR engine — alternative OCR backend behind the OCR_ENGINE setting.

Design constraints (7.9 GB RAM dev laptops, CPU-only target users):
- Lazy: torch + EasyOCR load on FIRST use, never at server startup.
- Single-slot cache: at most one engine instance held at a time, released
  after an idle timeout so RAM comes back when OCR is not in use.
- CPU by default; GPU used only when available AND OCR_ALLOW_GPU=1.
- Never loaded together with the chat/LLM model: Ollama models are managed
  by the Ollama server (keep_alive=0 is passed on OCR LLM/VLM calls, so the
  LLM unloads immediately after each request; see llm_extract.py).
"""
import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_IDLE_RELEASE_SECONDS = 120  # unload the torch model after 2 idle minutes

_CACHE = {"reader": None, "used_at": 0.0}

# Fine-tuned recognition networks live here (see ocr_train).
CUSTOM_NETWORK_DIR = (
    Path(__file__).resolve().parent.parent / "models" / "easyocr" / "user_network"
)


def _gpu_allowed():
    from django.conf import settings

    return bool(getattr(settings, "OCR_ALLOW_GPU", False))


def _resolve_gpu():
    if not _gpu_allowed():
        return False
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def _install_custom_weights(network, model_dir):
    """EasyOCR loads the custom .pth from the SAME directory as the detector;
    copy the trained weights there when missing or stale."""
    src = CUSTOM_NETWORK_DIR / f"{network}.pth"
    dst = Path(model_dir) / f"{network}.pth"
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dst)
        logger.info("Installed fine-tuned recognizer %s.pth -> %s", network, dst)
    return True


def _load_reader():
    import easyocr  # heavy: torch — imported only here
    from django.conf import settings

    use_gpu = _resolve_gpu()
    network = (getattr(settings, "OCR_EASYOCR_RECOG_NETWORK", "") or "").strip()
    if network and (CUSTOM_NETWORK_DIR / f"{network}.yaml").exists():
        model_dir = (
            getattr(settings, "OCR_EASYOCR_MODEL_DIR", "")
            or os.environ.get("EASYOCR_MODULE_PATH")
            or str(Path.home() / ".EasyOCR")
        )
        model_dir = Path(model_dir) / "model"
        if _install_custom_weights(network, model_dir):
            logger.info(
                "Loading EasyOCR reader (gpu=%s, recog_network=%s) — one-time lazy load",
                use_gpu, network,
            )
            return easyocr.Reader(
                ["en"], gpu=use_gpu, recog_network=network,
                user_network_directory=str(CUSTOM_NETWORK_DIR),
                model_storage_directory=str(model_dir),
                verbose=False,
            )
        logger.warning(
            "OCR_EASYOCR_RECOG_NETWORK=%s has no trained .pth in %s; using the stock model",
            network, CUSTOM_NETWORK_DIR,
        )
    logger.info("Loading EasyOCR reader (gpu=%s) — one-time lazy load", use_gpu)
    return easyocr.Reader(["en"], gpu=use_gpu, verbose=False)


def get_reader():
    """Return the cached EasyOCR reader, reloading it if it was released."""
    if _CACHE["reader"] is None:
        _CACHE["reader"] = _load_reader()
    _CACHE["used_at"] = time.monotonic()
    return _CACHE["reader"]


def release_idle_engine(max_idle_seconds=_IDLE_RELEASE_SECONDS):
    """Drop the cached reader when it has been idle for a while. Called at
    the start of every extraction; also safe to call from management code."""
    if _CACHE["reader"] is not None and time.monotonic() - _CACHE["used_at"] > max_idle_seconds:
        _CACHE["reader"] = None
        logger.info("EasyOCR reader released after idle timeout")


def force_release():
    _CACHE["reader"] = None


def easyocr_available():
    try:
        import easyocr  # noqa: F401

        return True
    except ImportError:
        return False


def _group_lines(results):
    """Merge boxes on the same visual row into one line (sorted left-to-right).

    EasyOCR emits one box per text region; on table rows the label, value,
    unit and reference columns come back as SEPARATE boxes, and the parser
    then reads the reference range ("< 140 / 90") as the value. Grouping by
    y-center (tolerance ~ median box height) reconstructs the row the way
    Tesseract reports it: "BLOOD PRESSURE 144 / 92 mmHg < 140 / 90".
    """
    import numpy as np

    items = []
    for bbox, text, conf in results:
        text = (text or "").strip()
        if not text:
            continue
        ys = [p[1] for p in bbox]
        xs = [p[0] for p in bbox]
        items.append((min(xs), min(ys), max(ys) - min(ys), text, float(conf)))
    if not items:
        return []
    med_h = float(np.median([it[2] for it in items])) or 1.0
    items.sort(key=lambda it: (it[1] + it[2] / 2))
    lines = []
    cluster = [items[0]]
    center = items[0][1] + items[0][2] / 2
    for it in items[1:]:
        c = it[1] + it[2] / 2
        if abs(c - center) <= max(0.6 * med_h, 0.5 * it[2]):
            cluster.append(it)
            center = sum(x[1] + x[2] / 2 for x in cluster) / len(cluster)
        else:
            lines.append(cluster)
            cluster = [it]
            center = c
    lines.append(cluster)

    out = []
    for cluster in lines:
        cluster.sort(key=lambda it: it[0])
        text = " ".join(it[3] for it in cluster)
        conf = sum(it[4] for it in cluster) / len(cluster)
        out.append({"text": text, "conf": round(min(conf, 1.0), 3)})
    return out


def ocr_image_easyocr(content: bytes):
    """Run EasyOCR over image bytes. Returns (lines, engine_info) in the same
    shape as ocr_engine.ocr_image: [{"text", "conf"}]."""
    import numpy as np

    from ocr.services.preprocess import decode_image, preprocess_image

    release_idle_engine()
    reader = get_reader()

    img = decode_image(content)
    processed = preprocess_image(img)
    # EasyOCR accepts numpy arrays; grayscale works but it prefers 3-channel.
    if processed.ndim == 2:
        processed = np.stack([processed] * 3, axis=-1)

    results = reader.readtext(processed, detail=1, paragraph=False)
    lines = _group_lines(results)

    engine_info = {"engine": "easyocr", "device": "gpu" if _gpu_allowed() and _torch_cuda() else "cpu"}
    return lines, engine_info


def _torch_cuda():
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False
