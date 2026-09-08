"""Document ingestion: text extraction + chunking with overlap."""
import hashlib
import logging

logger = logging.getLogger(__name__)

CHUNK_SIZE = 900   # characters
CHUNK_OVERLAP = 150


def extract_text(document):
    """Extract text from an uploaded file or the stored content_text field."""
    if document.file and document.file.name:
        name = document.file.name.lower()
        try:
            if name.endswith(".pdf"):
                from pypdf import PdfReader

                reader = PdfReader(document.file)
                pages = [(page.extract_text() or "") for page in reader.pages]
                return "\n\n".join(pages), {"pages": len(pages)}
            if name.endswith((".txt", ".md", ".text")):
                return document.file.read().decode("utf-8", errors="replace"), {}
        except Exception:
            logger.exception("Text extraction failed for %s", document.file.name)
            raise
    return document.content_text or "", {}


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Fixed-size overlapping character chunks. Sections (## / # headings)
    become metadata so citations can name the section."""
    if not text.strip():
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = end - overlap
    return chunks


def document_sha256(document):
    h = hashlib.sha256()
    if document.file and document.file.name:
        document.file.seek(0)
        for block in iter(lambda: document.file.read(65536), b""):
            h.update(block)
        document.file.seek(0)
    else:
        h.update((document.content_text or "").encode("utf-8"))
    return h.hexdigest()
