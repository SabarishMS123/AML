-- ============================================================
-- Non-destructive migration for existing projects.
--
-- Use this INSTEAD OF schema.sql if you already have data in Supabase and
-- don't want to drop your tables. Adds page-number tracking to
-- document_chunks and updates match_document_chunks() to return the
-- source file name + page number for citations.
--
-- Existing chunks (ingested before this upgrade) will have page_number =
-- NULL until their PDFs are re-ingested; the Policy Chatbot handles that
-- gracefully and just omits the page number for those older chunks.
-- ============================================================

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS page_number INT;

DROP FUNCTION IF EXISTS match_document_chunks(vector, float, int);

CREATE OR REPLACE FUNCTION match_document_chunks(
    query_embedding VECTOR(384),
    match_threshold FLOAT,
    match_count INT
)
RETURNS TABLE (
    id UUID,
    document_id UUID,
    content TEXT,
    similarity FLOAT,
    page_number INT,
    file_name VARCHAR
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.id,
        dc.document_id,
        dc.content,
        1 - (dc.embedding <=> query_embedding) AS similarity,
        dc.page_number,
        pd.file_name
    FROM document_chunks dc
    JOIN policy_documents pd ON pd.id = dc.document_id
    WHERE 1 - (dc.embedding <=> query_embedding) > match_threshold
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
