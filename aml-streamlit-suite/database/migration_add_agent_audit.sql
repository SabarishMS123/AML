-- ============================================================
-- Non-destructive migration: adds the agent investigation audit trail.
-- Run this against your existing Supabase project (it does not touch any
-- existing table). Also included in schema.sql for fresh installs.
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_investigations (
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

CREATE INDEX IF NOT EXISTS idx_agent_investigations_customer
    ON agent_investigations(customer_external_id);
CREATE INDEX IF NOT EXISTS idx_agent_investigations_created_at
    ON agent_investigations(created_at DESC);
