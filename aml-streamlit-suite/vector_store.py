"""Corrected ChromaDB-backed RAG pipeline for AML policy retrieval.

What was broken in the original pattern and how this version fixes it:

1) Retrieval lacked diagnostics: there was no explicit logging of the exact query,
   Chroma distances, and the raw chunks returned by the vector search. This made it
   impossible to tell whether the search was wrong or the embeddings were mismatched.

2) Persistence was missing: using a transient in-memory Chroma client causes all
   embeddings to disappear whenever the process restarts.

3) Embedding consistency was not guaranteed: the same model must be used for both
   ingestion and query, otherwise the vectors are not comparable.

4) Context grounding was weak: the retrieved chunks were not being joined into one
   clean `context_str` and the prompt did not strictly forbid answering from outside
   the provided context.

5) Low-similarity results were not handled: if the vector search returns weak matches,
    the code should fall back to a keyword-based search or a safe default.

This script is intentionally self-contained and runnable in a normal Python shell.
It stores data to a persistent local directory on disk and verifies the collection is
filled before queries are allowed.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger("aml_rag")
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

PERSIST_DIR = Path(__file__).resolve().parent / ".chroma_db"
COLLECTION_NAME = "aml_policy_chunks"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
DISTANCE_THRESHOLD = 0.85  # If Chroma returns distances above this, relevance is weak.

# Use a single shared embedding function instance for both ingestion and querying.
# This is the key fix for embedding alignment: all vectors MUST be created with the
# same model and same normalization rules.
embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL
)


# ---------------------------------------------------------------------------
# Example policy documents.
# ---------------------------------------------------------------------------
DEFAULT_POLICY_DOCS: list[dict[str, Any]] = [
    {
        "id": "doc-1",
        "text": (
            "Customer due diligence (CDD) must be completed before onboarding any high-risk"
            " customer. Enhanced due diligence is required for politically exposed persons"
            " and customers from high-risk jurisdictions."
        ),
        "metadata": {"source": "aml-policy", "category": "customer-due-diligence"},
    },
    {
        "id": "doc-2",
        "text": (
            "Suspicious activity reporting must be filed when a transaction exceeds internal"
            " alert thresholds or when multiple structured transactions appear designed to"
            " avoid reporting requirements."
        ),
        "metadata": {"source": "aml-policy", "category": "suspicious-activity"},
    },
    {
        "id": "doc-3",
        "text": (
            "Any transaction involving a sanctioned or restricted jurisdiction requires"
            " escalation to the compliance officer and enhanced review before approval."
        ),
        "metadata": {"source": "aml-policy", "category": "jurisdiction-review"},
    },
]


# ---------------------------------------------------------------------------
# Chroma client and collection setup.
# ---------------------------------------------------------------------------
def get_client() -> chromadb.PersistentClient:
    """Return a persistent client so embeddings survive app reloads.

    The original bug is caused by using an in-memory client (or creating a collection
    without a persistent path), which wipes the index whenever the process ends.
    """
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(PERSIST_DIR))


def get_collection() -> chromadb.Collection:
    """Get or create the collection with the same embedding function every time."""
    client = get_client()

    # Chroma raises InvalidCollectionException when the collection is missing.
    # Using get_or_create_collection is the correct, version-stable pattern and
    # ensures both ingestion and querying share the same embedding configuration.
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_function,
        metadata={"hnsw:space": "cosine"},
    )


def ingest_docs(docs: list[dict[str, Any]] | None = None) -> int:
    """Insert policy text documents into Chroma.

    A safety check is performed before search to ensure the index is not empty.
    """
    docs = docs or DEFAULT_POLICY_DOCS
    collection = get_collection()

    # Avoid duplicate ingestion when the app restarts and the collection already exists.
    if collection.count() > 0:
        logger.info("Collection already contains %s documents. Skipping re-ingest.", collection.count())
        return collection.count()

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for doc in docs:
        text = str(doc.get("text") or doc.get("content") or "").strip()
        if not text:
            continue
        ids.append(str(doc.get("id") or f"doc-{len(ids)}"))
        documents.append(text)
        metadatas.append(doc.get("metadata") or {})

    if not documents:
        raise ValueError("No documents were provided for ingestion.")

    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    logger.info("Ingested %s documents into collection '%s'.", len(documents), COLLECTION_NAME)
    return collection.count()


def ensure_collection_ready() -> chromadb.Collection:
    """Ensures the collection has data before queries are attempted."""
    collection = get_collection()
    if collection.count() == 0:
        logger.warning("Collection '%s' is empty; running ingestion before query.", COLLECTION_NAME)
        ingest_docs(DEFAULT_POLICY_DOCS)
    return collection


# ---------------------------------------------------------------------------
# Search and fallback logic.
# ---------------------------------------------------------------------------
def keyword_fallback_search(query: str, candidate_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fallback when Chroma distance is weak or no semantic match is found.

    This search ignores common stopwords so irrelevant questions like 'capital of France'
    do not accidentally match policy text just because it contains generic words like 'of'.
    """
    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "what", "when", "where",
        "why", "how", "who", "which", "this", "that", "these", "those", "of",
        "to", "in", "on", "for", "with", "and", "or", "be", "by", "as", "it",
        "at", "from", "if", "then", "before", "after", "must", "should", "can",
    }
    query_terms = {
        term.lower() for term in query.split() if term.strip() and term.lower() not in stopwords
    }
    if not query_terms:
        return []

    scored = []
    for item in candidate_docs:
        text = str(item.get("document") or "").lower()
        score = sum(1 for term in query_terms if term in text)
        if score > 0:
            scored.append({"score": score, "document": item})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return [entry["document"] for entry in scored[:5]]


def query_rag(question: str, match_count: int = 5) -> tuple[str, list[dict[str, Any]], float]:
    """Query ChromaDB and return a clean context string plus retrieved chunks.

    The debug output below makes the exact query text, the distance scores, and the
    retrieved chunks visible so we can diagnose retrieval quality immediately.
    """
    collection = ensure_collection_ready()

    logger.debug("Querying Chroma with question: %s", question)
    results = collection.query(
        query_texts=[question],
        n_results=match_count,
        include=["documents", "metadatas", "distances"],
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    logger.debug("Distance scores: %s", distances)
    logger.debug("Raw retrieved chunks: %s", documents)

    # If no docs are retrieved, return a safe default instead of hallucinating.
    if not documents:
        logger.warning("No docs were returned from Chroma for question '%s'.", question)
        return "No relevant compliance rule found", [], 1.0

    max_distance = max(distances) if distances else 0.0

    # Retry / fallback for weak semantic matches.
    if max_distance > DISTANCE_THRESHOLD:
        logger.warning(
            "Vector distances are weak (max_distance=%s > threshold=%s). Fallback search engaged.",
            max_distance,
            DISTANCE_THRESHOLD,
        )
        fallback_docs = keyword_fallback_search(question, [
            {"document": doc, "metadata": meta}
            for doc, meta in zip(documents, metadatas)
        ])
        if fallback_docs:
            documents = [item.get("document") or "" for item in fallback_docs]
            metadatas = [item.get("metadata") or {} for item in fallback_docs]
            distances = [1.0] * len(documents)
        else:
            return "No relevant compliance rule found", [], max_distance

    context_parts = []
    retrieved = []
    for idx, (doc, meta, dist) in enumerate(zip(documents, metadatas, distances), start=1):
        chunk_text = str(doc or "").strip()
        if not chunk_text:
            continue
        context_parts.append(f"[Excerpt {idx}] {chunk_text}")
        retrieved.append({
            "text": chunk_text,
            "metadata": meta or {},
            "distance": float(dist),
        })

    # This is the critical formatting fix: join the retrieved chunks into a clean
    # context string that the LLM can use as grounding material.
    context_str = "\n\n".join(context_parts)
    return context_str, retrieved, max_distance


# ---------------------------------------------------------------------------
# LLM answer generation with strict context grounding.
# ---------------------------------------------------------------------------
def generate_answer(question: str) -> str:
    """Return the answer, grounded in the retrieved context only."""
    context_str, retrieved_chunks, _ = query_rag(question)

    if not context_str or context_str == "No relevant compliance rule found":
        return "No relevant compliance rule found"

    system_prompt = (
        "You are an AML Compliance Assistant. Answer the question STRICTLY using the "
        "provided context below. If the answer cannot be found in the context, "
        "state 'No relevant compliance rule found'."
    )

    prompt = (
        f"Context:\n{context_str}\n\n"
        f"Question: {question}\n\n"
        "Answer using only the facts from the context above."
    )

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        # Some environments will not have an LLM key configured. In that case, return
        # a deterministic fallback instead of hallucinating.
        return (
            "No relevant compliance rule found"
            if not retrieved_chunks
            else context_str
        )

    try:
        from groq import Groq
    except Exception as exc:  # pragma: no cover
        logger.exception("Groq library is unavailable: %s", exc)
        return "No relevant compliance rule found"

    client = Groq(api_key=api_key)
    model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=300,
    )

    answer = response.choices[0].message.content.strip()
    return answer or "No relevant compliance rule found"


# ---------------------------------------------------------------------------
# Demo run.
# ---------------------------------------------------------------------------
def demo() -> None:
    """Small runnable example to verify the pipeline end-to-end."""
    logger.info("Initializing persistent Chroma collection at %s", PERSIST_DIR)
    ingest_docs(DEFAULT_POLICY_DOCS)

    sample_questions = [
        "What due diligence is required before onboarding a high-risk customer?",
        "When should a suspicious activity report be filed?",
        "What happens when a transaction is tied to a sanctioned jurisdiction?",
        "What is the capital of France?",
    ]

    for q in sample_questions:
        print(f"\nQUESTION: {q}")
        answer = generate_answer(q)
        print(f"ANSWER: {answer}")


if __name__ == "__main__":
    demo()
