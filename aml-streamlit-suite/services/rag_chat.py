"""
services/rag_chat.py

Retrieval-Augmented Generation chat engine for the Policy Chatbot tab.

Flow:
  1. Normalize + embed the user's question locally (Sentence-Transformers)
  2. Vector-search Supabase (pgvector, via the match_document_chunks RPC,
     cosine similarity)
  3. Build a context block from the top matching policy chunks
  4. Ask Groq (llama-3.3-70b-versatile) to answer, citing the retrieved clauses

Retrieval tuning (see project brief):
  - match_threshold lowered from 0.2 -> 0.12 so genuinely relevant chunks
    that use different phrasing than the question (e.g. "politically
    exposed person" vs "PEP policy") aren't dropped before the LLM ever
    sees them. The floor that triggers the keyword-search fallback was
    lowered correspondingly.
  - match_count (top_k) raised from an inconsistent 5 to a steady 5, with
    the AML agent's own internal lookup bumped from 4 to 5 as well so both
    call sites are consistent.
  - Queries are normalized (trimmed, stray quotes stripped, whitespace
    collapsed) before embedding, so a pasted '"What is PEP policy?"' embeds
    the same as the plain version.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from groq import Groq

from database.supabase_client import get_supabase_client
from services.embeddings import embed_text
from utils.formatting import normalize_query

logger = logging.getLogger(__name__)

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Lowered from 0.2: cosine similarity on short policy clauses regularly
# lands in the 0.12-0.25 band for genuinely relevant matches, and the old
# 0.2 floor combined with the 0.15 fallback-trigger was silently discarding
# good hits for common questions like "What is PEP policy?".
MATCH_THRESHOLD = 0.12
FALLBACK_TRIGGER_SIMILARITY = 0.10
MATCH_COUNT = 5  # top_k, per tuning brief (4-5 chunks)
EMBEDDING_DIMENSIONS = 384

SYSTEM_PROMPT = """You are an AML Compliance Assistant. Answer the question STRICTLY using the provided context below. If the answer cannot be found in the context, state 'No relevant compliance rule found'."""


@dataclass
class RetrievedChunk:
    id: str
    document_id: str
    content: str
    similarity: float
    page_number: int | None = None
    document_name: str | None = None


@dataclass
class ChatResponse:
    answer: str
    sources: list[RetrievedChunk]


def _get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY is not set in your .env file.")
    return Groq(api_key=api_key)


def _fallback_keyword_search(question: str, limit: int = 5) -> list[dict]:
    """Fallback search used when the vector similarity is weak or empty.

    This is a conservative text-match check against the stored chunks, and it
    acts as a safety net when semantic retrieval returns low-confidence results.
    """
    client = get_supabase_client()
    resp = (
        client.table("document_chunks")
        .select("id, document_id, content, page_number, policy_documents(file_name)")
        .execute()
    )
    rows = resp.data or []

    if not rows:
        return []

    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "what", "when", "where",
        "why", "how", "who", "which", "this", "that", "these", "those", "of",
        "to", "in", "on", "for", "with", "and", "or", "be", "by", "as", "it",
        "at", "from", "if", "then", "before", "after", "must", "should", "can"
    }
    query_terms = {
        term.lower() for term in question.split() if term.strip() and term.lower() not in stopwords
    }
    if not query_terms:
        return []

    scored = []
    for row in rows:
        content = str(row.get("content") or "").lower()
        score = sum(1 for term in query_terms if term in content)
        if score > 0:
            scored.append({"row": row, "score": score})

    scored.sort(key=lambda item: item["score"], reverse=True)
    results = []
    for item in scored[:limit]:
        row = item["row"]
        joined = row.get("policy_documents") or {}
        results.append({
            "id": row["id"],
            "document_id": row["document_id"],
            "content": row["content"],
            "page_number": row.get("page_number"),
            "file_name": joined.get("file_name") if isinstance(joined, dict) else None,
            "similarity": 0.0,  # keyword match has no cosine score
        })
    return results


def retrieve_relevant_chunks(question: str, match_count: int = MATCH_COUNT,
                              match_threshold: float = MATCH_THRESHOLD) -> list[RetrievedChunk]:
    """Retrieve top policy chunks and log the exact query and score details."""
    client = get_supabase_client()
    normalized_question = normalize_query(question)
    query_embedding = embed_text(normalized_question)
    if len(query_embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Expected a {EMBEDDING_DIMENSIONS}-dimensional embedding, "
            f"got {len(query_embedding)} dimensions."
        )

    logger.debug("RAG query (normalized): %s", normalized_question)
    logger.debug("Query embedding length: %s", len(query_embedding))

    resp = client.rpc(
        "match_document_chunks",
        {
            "query_embedding": query_embedding,
            "match_threshold": match_threshold,
            "match_count": match_count,
        },
    ).execute()

    rows = resp.data or []
    logger.debug("Vector retrieval row count: %s", len(rows))
    for row in rows:
        logger.debug(
            "Retrieved chunk id=%s similarity=%s page=%s doc=%s",
            row.get("id"),
            row.get("similarity"),
            row.get("page_number"),
            row.get("file_name"),
        )

    # If semantic retrieval returned nothing or only weakly relevant rows,
    # fall back to a textual search instead of returning a misleading answer.
    if not rows:
        logger.warning("No semantic matches returned for question '%s'. Triggering keyword fallback.", normalized_question)
        rows = _fallback_keyword_search(normalized_question, limit=match_count)
        if not rows:
            logger.warning("No relevant policy text found for question '%s'.", normalized_question)
            return []
    else:
        max_similarity = max(float(r.get("similarity", 0.0)) for r in rows)
        logger.debug("Max similarity returned by vector search: %s", max_similarity)

        if max_similarity < FALLBACK_TRIGGER_SIMILARITY:
            logger.warning(
                "Vector similarity too low (%.4f). Falling back to keyword search.",
                max_similarity,
            )
            keyword_rows = _fallback_keyword_search(normalized_question, limit=match_count)
            if keyword_rows:
                rows = keyword_rows
            elif not rows:
                logger.warning("Keyword fallback also found no relevant results for '%s'.", normalized_question)
                return []

    return [
        RetrievedChunk(
            id=str(row["id"]),
            document_id=str(row["document_id"]),
            content=str(row["content"]),
            similarity=float(row.get("similarity", 0.0)),
            page_number=row.get("page_number"),
            document_name=row.get("file_name"),
        )
        for row in rows
    ]


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for i, c in enumerate(chunks, start=1):
        label = c.document_name or "Policy document"
        if c.page_number:
            label += f", p. {c.page_number}"
        parts.append(f"[Excerpt {i}] ({label}, similarity={c.similarity:.2f})\n{c.content}")
    return "\n\n".join(parts)


def answer_question(question: str, chat_history: list[dict] | None = None) -> ChatResponse:
    """Answer a policy question using ground-truth policy excerpts only."""
    chunks = retrieve_relevant_chunks(question)

    if not chunks:
        return ChatResponse(
            answer="No relevant compliance rule found",
            sources=[],
        )

    context_block = build_context_block(chunks)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if chat_history:
        messages.extend(chat_history[-6:])
    messages.append({
        "role": "user",
        "content": f"Policy context:\n\n{context_block}\n\nQuestion: {normalize_query(question)}",
    })

    client = _get_groq_client()
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=800,
    )
    answer = completion.choices[0].message.content.strip() or "No relevant compliance rule found"

    return ChatResponse(answer=answer, sources=chunks)
