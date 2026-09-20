"""
services/pdf_rag.py

Handles ingestion of AML policy PDF documents:
  1. Extract text with pypdf, per page (so we can cite page numbers later)
  2. Split each page into ~800-1000 word chunks with 150-word overlap
  3. Generate local embeddings via Sentence-Transformers
  4. Persist metadata + chunk embeddings (+ originating page number) into
     Supabase, so the chatbot can cite "Document, p. N" for every answer.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from pypdf import PdfReader

from database.supabase_client import get_supabase_client
from services.embeddings import embed_texts

# Tuned retrieval chunking: bigger chunks with meaningful overlap retrieve
# more coherent policy clauses than the previous 500/50-word setting, which
# too often split a single requirement (e.g. a PEP definition) across two
# chunks and made both halves individually low-similarity at query time.
CHUNK_SIZE_WORDS = 900
CHUNK_OVERLAP_WORDS = 150


@dataclass
class IngestResult:
    document_id: str
    file_name: str
    num_chunks: int


@dataclass
class PageChunk:
    page_number: int
    text: str


def extract_pages_from_pdf(file_bytes: bytes) -> list[tuple[int, str]]:
    """Extract raw text from a PDF file's bytes, per page (1-indexed)."""
    reader = PdfReader(io.BytesIO(file_bytes))
    pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append((i, text))
    return pages


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Backward-compatible helper: full document text, all pages joined."""
    return "\n".join(text for _, text in extract_pages_from_pdf(file_bytes))


def _chunk_words(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    step = max(chunk_size - overlap, 1)
    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))
        if end >= len(words):
            break
        start += step
    return chunks


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_WORDS,
               overlap: int = CHUNK_OVERLAP_WORDS) -> list[str]:
    """Split text into overlapping word-based chunks.

    Word count is used as a lightweight, dependency-free proxy for token
    count (roughly ~0.75 words per token in English, close enough for
    chunking purposes). Kept for backward compatibility / non-page use.
    """
    return _chunk_words(text, chunk_size, overlap)


def chunk_pages(pages: list[tuple[int, str]], chunk_size: int = CHUNK_SIZE_WORDS,
                 overlap: int = CHUNK_OVERLAP_WORDS) -> list[PageChunk]:
    """Chunk text page-by-page so every chunk can be traced back to the
    exact page it came from (needed for source citations in the chatbot).
    """
    page_chunks: list[PageChunk] = []
    for page_number, text in pages:
        for chunk in _chunk_words(text, chunk_size, overlap):
            if chunk.strip():
                page_chunks.append(PageChunk(page_number=page_number, text=chunk))
    return page_chunks


def ingest_policy_pdf(file_bytes: bytes, file_name: str) -> IngestResult:
    """Full ingestion pipeline for one uploaded PDF file.

    Returns an IngestResult with the new document_id and chunk count, or
    raises an exception on failure (caught by the Streamlit UI layer).
    """
    client = get_supabase_client()

    pages = extract_pages_from_pdf(file_bytes)
    if not any(text.strip() for _, text in pages):
        raise ValueError(
            f"No extractable text found in '{file_name}'. "
            "It may be a scanned/image-only PDF."
        )

    page_chunks = chunk_pages(pages)
    if not page_chunks:
        raise ValueError(f"'{file_name}' produced zero chunks after splitting.")

    # 1. Insert policy_documents row
    doc_insert = client.table("policy_documents").insert({
        "file_name": file_name,
        "file_path": f"uploads/{file_name}",
    }).execute()
    document_id = doc_insert.data[0]["id"]

    # 2. Embed all chunks in one batch call (efficient)
    vectors = embed_texts([pc.text for pc in page_chunks])

    # 3. Bulk insert document_chunks (with originating page number)
    rows = [
        {
            "document_id": document_id,
            "content": pc.text,
            "embedding": vector,
            "page_number": pc.page_number,
        }
        for pc, vector in zip(page_chunks, vectors)
    ]
    # Supabase/PostgREST handles reasonably large batch inserts; split into
    # sub-batches to stay well under payload limits for very large PDFs.
    BATCH = 100
    for i in range(0, len(rows), BATCH):
        client.table("document_chunks").insert(rows[i:i + BATCH]).execute()

    return IngestResult(document_id=document_id, file_name=file_name, num_chunks=len(rows))


def list_policy_documents() -> list[dict]:
    client = get_supabase_client()
    resp = client.table("policy_documents").select("*").order("uploaded_at", desc=True).execute()
    return resp.data

def delete_policy_document(document_id: str) -> None:
    """Delete a policy document and all its associated vector chunks from Supabase."""
    client = get_supabase_client()
    # Delete chunks first to avoid foreign key constraints (if CASCADE isn't set)
    client.table("document_chunks").delete().eq("document_id", document_id).execute()
    # Delete parent document row
    client.table("policy_documents").delete().eq("id", document_id).execute()

def delete_all_policy_documents() -> None:
    """Remove all policy documents and vector chunks from the database."""
    client = get_supabase_client()
    client.table("document_chunks").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    client.table("policy_documents").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
