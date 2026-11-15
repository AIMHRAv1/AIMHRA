"""Image degradations approximating real phone photography.

Degradations are SYNTHETIC — they approximate but do not reproduce real
photos (stated in every output). Fixed RNG seed per card keeps the corpus
reproducible.
"""
import random

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def degrade(png_bytes, kind, seed=0):
    """Apply one degradation to PNG bytes; returns PNG bytes. `clean` is a
    JPEG re-encode at quality 92 to keep file handling uniform."""
    rng = random.Random(seed)
    img = Image.open(__import__("io").BytesIO(png_bytes)).convert("RGB")

    if kind == "clean":
        out = _jpeg(img, 92)
    elif kind == "rot":
        angle = rng.choice([-5, -3, 3, 5])
        out = img.rotate(angle, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
        out = _jpeg(out, 90)
    elif kind == "blur":
        out = _jpeg(img.filter(ImageFilter.GaussianBlur(2.0)), 88)
    elif kind == "noise":
        arr = np.array(img).astype(np.int16)
        arr += np.random.RandomState(rng.randrange(1 << 30)).normal(0, 16, arr.shape).astype(np.int16)
        out = _jpeg(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), 88)
    elif kind == "lowres":
        w, h = img.size
        out = img.resize((w // 3, h // 3)).resize((w, h), Image.BILINEAR)
        out = _jpeg(out, 85)
    elif kind == "lighting":
        # Uneven lighting: horizontal brightness gradient + contrast loss.
        arr = np.array(img).astype(np.float32)
        gradient = np.linspace(0.55, 1.15, arr.shape[1], dtype=np.float32)
        arr *= gradient[None, :, None]
        out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        out = _jpeg(ImageEnhance.Contrast(out).enhance(0.75), 88)
    elif kind == "jpeg":
        out = _jpeg(img, 30)  # heavy compression artifacts
    elif kind == "perspective":
        out = _perspective(img, rng)
        out = _jpeg(out, 88)
    else:
        raise ValueError(f"Unknown degradation: {kind}")
    return _to_png_bytes(out)


def _jpeg(img, quality):
    buf = __import__("io").BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _perspective(img, rng):
    """Quadrilateral warp imitating a tilted phone shot."""
    import cv2

    arr = np.array(img)
    h, w = arr.shape[:2]
    shift = rng.randint(20, 60)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([
        [rng.randint(0, shift), rng.randint(0, shift // 2)],
        [w - rng.randint(0, shift), rng.randint(0, shift // 2)],
        [w - rng.randint(0, shift // 2), h - rng.randint(0, shift)],
        [rng.randint(0, shift // 2), h - rng.randint(0, shift)],
    ])
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(arr, matrix, (w, h), borderValue=(255, 255, 255))
    return Image.fromarray(warped)


def _to_png_bytes(img):
    buf = __import__("io").BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


DEGRADATIONS = ["clean", "rot", "blur", "noise", "lowres", "lighting", "jpeg", "perspective"]
