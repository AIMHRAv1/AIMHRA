"""Upload safety: real file type via magic bytes, size cap, safe naming.

The client-provided file name is ignored entirely (never used on disk);
content is validated by magic bytes so a renamed file cannot pass as an image.
"""
import os
import pathlib
import tempfile

from ocr.exceptions import UploadValidationError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

# (canonical type, magic-byte prefixes)
_SIGNATURES = (
    ("jpg", (b"\xff\xd8\xff",)),
    ("png", (b"\x89PNG\r\n\x1a\n",)),
    ("pdf", (b"%PDF",)),
)


def validate_upload(django_file):
    """Return (file_type, content_bytes) for an allowed, in-size upload.

    Raises UploadValidationError with a user-safe message otherwise. Reads
    the whole file into memory (capped at 5 MB) and ignores the client name.
    """
    if django_file is None:
        raise UploadValidationError("No file uploaded. Attach a JPG, PNG or PDF report card.")
    content = django_file.read()
    if len(content) == 0:
        raise UploadValidationError("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadValidationError("File is too large. Maximum size is 5 MB.")

    file_type = sniff_type(content)
    if file_type is None:
        raise UploadValidationError(
            "Unsupported file. Only JPG, PNG or PDF report cards are accepted "
            "(the file content did not match its type)."
        )
    return file_type, content


def sniff_type(content: bytes):
    """Return 'jpg' | 'png' | 'pdf' by magic bytes, else None."""
    for file_type, prefixes in _SIGNATURES:
        if any(content.startswith(p) for p in prefixes):
            return file_type
    return None


def temp_file_path(file_type: str, content: bytes):
    """Write content to a NamedTemporaryFile (never client-controlled name)
    and return its path. Caller must delete it via cleanup()."""
    suffix = f".{file_type}"
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(content)
    return str(pathlib.Path(path))


def cleanup(path):
    """Best-effort deletion of the temporary upload copy."""
    try:
        pathlib.Path(path).unlink(missing_ok=True)
    except OSError:
        pass
