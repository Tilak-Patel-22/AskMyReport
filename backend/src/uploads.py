"""User-uploaded PDFs: parse -> chunk -> embed -> store in the "uploads" Chroma collection.

Runs the exact library pipeline (ingest.parse_pdf, chunk.doc_chunks, the bge embedding model), so an uploaded PDF is
indexed like the 12 reports. Uploads live in their own collection: library searches never see them, and a question
about an upload only searches that upload (retrieve.ranked_upload). The PDF file itself is deleted after indexing.
"""
import os
import tempfile
import uuid
from pathlib import Path

from chunk import doc_chunks
from ingest import parse_pdf
from retrieve import model
from vectorstore import BATCH, get_collection

MAX_BYTES = 50 * 1024 * 1024  # 50 MB, about a 500-page annual report


class UploadError(ValueError):
    """The file can't be indexed; the message is safe to show the user."""


def exists(upload_id: str) -> bool:
    return bool(get_collection("uploads").get(where={"upload_id": upload_id}, limit=1, include=[])["ids"])


def index_pdf(data: bytes, filename: str) -> dict:
    """Index one uploaded PDF and return {upload_id, filename, pages, chunks}. Raises UploadError for bad files."""
    if not data.startswith(b"%PDF"):
        raise UploadError("That file isn't a PDF.")
    if len(data) > MAX_BYTES:
        raise UploadError("That PDF is larger than 50 MB.")
    filename = Path(filename or "document.pdf").name[:120]  # display name only; never used as a path
    upload_id = uuid.uuid4().hex

    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        doc = parse_pdf(Path(tmp))  # pages without a text layer are skipped and logged
    except Exception as e:  # corrupted / encrypted file
        raise UploadError("Couldn't read that PDF (it may be damaged or password-protected).") from e
    finally:
        os.unlink(tmp)

    doc.update(company=filename, year="")  # sources show "<filename> · p. N"
    chunks, _ = doc_chunks(doc, prefix=upload_id)
    if not chunks:
        raise UploadError("No text found in that PDF. Scanned (image-only) PDFs aren't supported yet.")

    vectors = model().encode([c["text"] for c in chunks], batch_size=32)
    col = get_collection("uploads")
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        col.add(
            ids=[c["chunk_id"] for c in batch],
            embeddings=vectors[i:i + BATCH],
            documents=[c["text"] for c in batch],
            metadatas=[{"upload_id": upload_id, "company": filename, "year": "", "page_number": c["page_number"]} for c in batch],
        )
    return {"upload_id": upload_id, "filename": filename, "pages": len(doc["pages"]), "chunks": len(chunks)}
