import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from pypdf import PdfReader

from kb.models import DocumentChunk, KnowledgeDocument
from kb.services.ingestion import _HEADING_RE


class Command(BaseCommand):
    help = "Backfill verifiable PDF page and section metadata without reindexing chunks."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", type=int)

    def handle(self, *args, **options):
        documents = KnowledgeDocument.objects.prefetch_related("chunks").order_by("id")
        if options["document_id"]:
            documents = documents.filter(pk=options["document_id"])

        updated_documents = 0
        for document in documents:
            if not document.file or not document.file.name:
                continue
            path = Path(document.file.path)
            if path.suffix.lower() != ".pdf":
                continue
            if not path.is_file():
                self.stderr.write(
                    self.style.WARNING(
                        f"Skipping document {document.id}: source PDF is missing ({path})."
                    )
                )
                continue

            try:
                pages = self._read_pages(path)
            except Exception as exc:
                raise CommandError(
                    f"Could not read source PDF for document {document.id}: {exc}"
                ) from exc

            updated = self._update_chunks(document, pages)
            if updated:
                updated_documents += 1
            self.stdout.write(
                f"Document {document.id}: updated {updated} chunk metadata records."
            )

        if updated_documents == 0:
            self.stdout.write("No chunk metadata needed updating.")

    @staticmethod
    def _read_pages(path):
        pages = []
        for page_number, page in enumerate(PdfReader(path).pages, start=1):
            text = page.extract_text() or ""
            normalized = " ".join(text.lower().split())
            headings = []
            cursor = 0
            for raw_line in text.splitlines():
                line = re.sub(
                    r"^\d+(?=Chapter\b)", "", raw_line.strip(), flags=re.IGNORECASE
                )
                cleaned = " ".join(line.split())
                if cleaned and len(cleaned) <= 180 and _HEADING_RE.match(cleaned):
                    position = normalized.find(cleaned.lower(), cursor)
                    if position >= 0:
                        headings.append((position, cleaned))
                        cursor = position + len(cleaned)
            pages.append((normalized, headings, normalized.startswith("contents ")))
        return pages

    @staticmethod
    def _update_chunks(document, pages):
        chunks = list(document.chunks.order_by("chunk_index"))
        changes = []

        for chunk in chunks:
            normalized_text = " ".join(chunk.text.lower().split())
            if len(normalized_text) < 80:
                continue
            candidates = []
            for page_number, (page_text, headings, is_contents) in enumerate(pages, start=1):
                for prefix_length in (200, 160, 120, 80):
                    position = page_text.find(normalized_text[:prefix_length])
                    if position >= 0:
                        candidates.append(
                            (prefix_length, page_number, position, headings, is_contents)
                        )
                        break

            if not candidates:
                continue
            best_length = max(candidate[0] for candidate in candidates)
            best_candidates = [
                candidate for candidate in candidates if candidate[0] == best_length
            ]
            if len(best_candidates) > 1:
                current_page = next(
                    (
                        candidate
                        for candidate in best_candidates
                        if candidate[1] == chunk.page_number
                    ),
                    None,
                )
                if current_page is None:
                    continue
                selected = current_page
            else:
                selected = best_candidates[0]
            _, page_number, position, headings, is_contents = selected
            _, page_number, position, headings, is_contents = selected
            if chunk.page_number is None:
                chunk.page_number = page_number

            is_contents_chunk = is_contents or re.search(
                r"(?:\bcontents\s+acknowledgements\b|"
                r"\backnowledgements\s+v\s+acronyms\s+and\s+abbreviations\b)",
                normalized_text,
            )
            if not is_contents_chunk:
                section = next(
                    (
                        title
                        for title in _chunk_headings(chunk.text)
                    ),
                    "",
                )
                if not section:
                    section = next(
                        (
                            title
                            for heading_position, title in reversed(headings)
                            if heading_position <= position
                        ),
                        "",
                    )
                if section:
                    chunk.section = section[:255]
            changes.append(chunk)

        if changes:
            DocumentChunk.objects.bulk_update(changes, ["page_number", "section"], batch_size=200)
        return len(changes)


def _chunk_headings(text):
    for raw_line in text.splitlines():
        line = re.sub(r"^\d+(?=Chapter\b)", "", raw_line.strip(), flags=re.IGNORECASE)
        cleaned = " ".join(line.split())
        if cleaned and len(cleaned) <= 180 and _HEADING_RE.match(cleaned):
            yield cleaned
