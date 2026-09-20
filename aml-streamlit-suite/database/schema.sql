-- ============================================================
-- AML Compliance Suite - Supabase (PostgreSQL + pgvector) schema
-- Run this entire script in the Supabase SQL Editor.
-- ============================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Drop existing objects if re-running (safe for dev/reset only)
DROP TABLE IF EXISTS agent_investigations CASCADE;
DROP TABLE IF EXISTS risk_assessments CASCADE;
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS policy_documents CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP FUNCTION IF EXISTS match_document_chunks(vector, float, int);

-- Customers Table
CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    country VARCHAR(100),
    risk_level VARCHAR(20) DEFAULT 'LOW' CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Transactions Table
CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id VARCHAR(100) UNIQUE NOT NULL,
    customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,
    amount NUMERIC(15, 2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'USD',
    sender_country VARCHAR(100),
    receiver_country VARCHAR(100),
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    transaction_type VARCHAR(50)
);

CREATE INDEX idx_transactions_customer_id ON transactions(customer_id);
CREATE INDEX idx_transactions_timestamp ON transactions(timestamp);

-- Policy Documents Table
CREATE TABLE policy_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Document Chunks Table (384-dim for all-MiniLM-L6-v2)
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES policy_documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding VECTOR(384),
    page_number INT
);

-- Vector index for faster similarity search (IVFFlat, cosine distance)
CREATE INDEX idx_document_chunks_embedding
    ON document_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Risk Assessments Log Table
CREATE TABLE risk_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,
    risk_level VARCHAR(20) NOT NULL,
    flags JSONB NOT NULL,
    reasoning TEXT NOT NULL,
    evaluated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_risk_assessments_customer_id ON risk_assessments(customer_id);

-- Agent Investigation Audit Trail
-- Every run of the AML Compliance Investigation Agent (agents/) is logged
-- here: the user's request, the full tool-call trace, the parsed final
-- report, and whether a recommended risk update was approved by a human.
CREATE TABLE agent_investigations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_external_id VARCHAR(100),
    user_request TEXT NOT NULL,
    tool_trace JSONB NOT NULL DEFAULT '[]',
    risk_level VARCHAR(30),
    insufficient_information BOOLEAN DEFAULT FALSE,
    suspicious_patterns JSONB DEFAULT '[]',
    evidence JSONB DEFAULT '[]',
    policy_references JSONB DEFAULT '[]',
    analysis TEXT,
    recommended_action TEXT,
    risk_update_recommendation JSONB,
    risk_update_approved BOOLEAN DEFAULT FALSE,
    raw_report TEXT,
    truncated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_agent_investigations_customer ON agent_investigations(customer_external_id);
CREATE INDEX idx_agent_investigations_created_at ON agent_investigations(created_at DESC);

-- Cosine Similarity Match RPC Function
-- Returns the originating document's file_name and page_number alongside
-- each chunk so the Policy Chatbot can render a proper source citation
-- ("Document.pdf, p. 4") instead of just a raw chunk id.
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
