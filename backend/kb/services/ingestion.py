"""Document ingestion: text extraction + chunking with overlap."""
import hashlib
import logging
import re

logger = logging.getLogger(__name__)

CHUNK_SIZE = 900   # characters
CHUNK_OVERLAP = 150
_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s+.+|"
    r"(?:(?i:Chapter|Annex|Appendix)\s+\d+\b).{3,}|"
    r"\d{1,2}(?:\.\d{1,2})*[.)]?\s+[A-Z][^.!?]{2,120}|"
    r"[A-Z]\.\d{1,2}(?:\.\d{1,2})*:\s+.{3,}|"
    r"(?i:RECOMMENDATION)\s+[A-Z0-9.]+:\s+.{3,}|"
    r"(?i:Executive summary|References|Acknowledgements))\s*$",
)


def extract_text(document):
    """Extract text from an uploaded file or the stored content_text field."""
    if document.file and document.file.name:
        name = document.file.name.lower()
        try:
            if name.endswith(".pdf"):
                from pypdf import PdfReader

                reader = PdfReader(document.file)
                pages = [(page.extract_text() or "") for page in reader.pages]
                return "\n\n".join(pages), {"pages": len(pages), "page_texts": pages}
            if name.endswith((".txt", ".md", ".text")):
                return document.file.read().decode("utf-8", errors="replace"), {"page_texts": None}
        except Exception:
            logger.exception("Text extraction failed for %s", document.file.name)
            raise
    return document.content_text or "", {"page_texts": None}


def chunk_document(document):
    """Return chunk text and its source page when page boundaries are available."""
    text, metadata = extract_text(document)
    pages = metadata.get("page_texts")
    if pages is None:
        return _chunk_page(text, None), metadata

    chunks = []
    for page_number, page_text in enumerate(pages, start=1):
        chunks.extend(_chunk_page(page_text, page_number))
    return chunks, metadata


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split at paragraph/sentence boundaries while retaining overlap."""
    return [chunk for chunk, _page, _section in _chunk_page(text, None, chunk_size, overlap)]


def _chunk_page(text, page_number, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    if not text.strip():
        return []

    section = ""
    paragraphs = []
    current_lines = []
    for line in text.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            if current_lines:
                paragraphs.append(("\n".join(current_lines).strip(), section))
                current_lines = []
            continue
        stripped_line = re.sub(r"^\d+(?=Chapter\b)", "", stripped_line, flags=re.IGNORECASE)
        if _HEADING_RE.match(stripped_line) and len(stripped_line) <= 180:
            if current_lines:
                paragraphs.append(("\n".join(current_lines).strip(), section))
                current_lines = []
            paragraph = stripped_line
            section = re.sub(r"^#{1,6}\s*", "", paragraph).strip()
            paragraphs.append((paragraph, section))
        else:
            current_lines.append(stripped_line)
    if current_lines:
        paragraphs.append(("\n".join(current_lines).strip(), section))

    chunks = []
    current_text = []
    current_section = ""
    current_length = 0

    def flush():
        nonlocal current_text, current_section, current_length
        if current_text:
            chunks.append(("\n\n".join(current_text), page_number, current_section))
            current_text = []
            current_section = ""
            current_length = 0

    for paragraph, paragraph_section in paragraphs:
        pieces = _split_long_paragraph(paragraph, chunk_size, overlap) if len(paragraph) > chunk_size else [paragraph]
        if current_text and paragraph_section != current_section:
            flush()
        for piece in pieces:
            if current_text and current_length + len(piece) + 2 > chunk_size:
                flush()
            if not current_text:
                current_section = paragraph_section
            current_text.append(piece)
            current_length += len(piece) + 2
    flush()
    return chunks


def _split_long_paragraph(paragraph, chunk_size, overlap):
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    if len(sentences) == 1:
        return _split_at_words(paragraph, chunk_size, overlap)

    chunks = []
    current = ""
    for sentence in sentences:
        if len(sentence) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_at_words(sentence, chunk_size, overlap))
        elif current and len(current) + len(sentence) + 1 > chunk_size:
            chunks.append(current)
            overlap_text = current[-overlap:].lstrip() if overlap else ""
            current = (
                f"{overlap_text} {sentence}".strip()
                if len(overlap_text) + len(sentence) + 1 <= chunk_size
                else sentence
            )
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def _split_at_words(text, chunk_size, overlap):
    words = text.split()
    chunks = []
    current = []
    current_length = 0
    for word in words:
        if current and current_length + len(word) + 1 > chunk_size:
            piece = " ".join(current)
            chunks.append(piece)
            overlap_words = []
            overlap_length = 0
            for prior in reversed(current):
                if overlap_length + len(prior) + 1 > overlap:
                    break
                overlap_words.insert(0, prior)
                overlap_length += len(prior) + 1
            current = overlap_words
            current_length = overlap_length
        current.append(word)
        current_length += len(word) + 1
    if current:
        chunks.append(" ".join(current))
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
