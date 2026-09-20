"""
services/aml_agent.py

Two-stage AML risk evaluation agent:

  Stage 1 - Deterministic Rule Engine
    Scans each customer's transactions for classic AML red flags:
      - Large transactions (> $10,000)
      - Velocity (> 5 transactions within any 1-hour window)
      - Cross-border transfers involving a high-risk country
      - Structuring (multiple transactions between $9,000 and $9,999)

  Stage 2 - Groq LLM Policy Reasoning
    For any customer with 1+ flags, retrieves relevant policy chunks and
    asks Groq (llama-3.3-70b-versatile) to assign a final risk level with
    an audit-ready justification, citing the policy text used.

Results are persisted to `risk_assessments` and `customers.risk_level`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import timedelta

import pandas as pd
from groq import Groq

from database.supabase_client import get_supabase_client
from services.embeddings import embed_text
from utils.formatting import normalize_query

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

LARGE_TXN_THRESHOLD = 10_000
VELOCITY_WINDOW_HOURS = 1
VELOCITY_COUNT_THRESHOLD = 5
STRUCTURING_LOW = 9_000
STRUCTURING_HIGH = 9_999

# Sample high-risk country / jurisdiction list (aligned loosely with
# FATF-style "increased monitoring" categories). Customize as needed.
HIGH_RISK_COUNTRIES = {
    "iran", "north korea", "myanmar", "afghanistan", "syria",
    "yemen", "south sudan", "somalia", "venezuela", "belarus",
}

RISK_REASONING_SYSTEM_PROMPT = """You are a senior AML compliance analyst.
You are given a customer's rule-engine flags, a summary of their transaction
activity, and relevant excerpts from the institution's AML policy.

Decide a final risk level: HIGH, MEDIUM, or LOW.
Respond ONLY as JSON, with no markdown fences and no extra text, in this exact shape:
{"risk_level": "HIGH" | "MEDIUM" | "LOW", "reasoning": "<2-4 sentence audit justification citing the policy excerpts by number>"}
The "reasoning" value must be plain prose or a plain markdown table only — never use raw HTML tags such as <br>.
"""


@dataclass
class RuleFlag:
    rule: str
    detail: str


@dataclass
class CustomerEvaluation:
    customer_id: str
    external_id: str
    full_name: str
    flags: list[RuleFlag] = field(default_factory=list)
    risk_level: str = "LOW"
    reasoning: str = "No red flags detected by the rule engine."
    transaction_count: int = 0
    total_volume: float = 0.0


# ---------------------------------------------------------------------
# Stage 1: Deterministic rule engine
# ---------------------------------------------------------------------

def _flag_large_transactions(txns: pd.DataFrame) -> list[RuleFlag]:
    large = txns[txns["amount"] > LARGE_TXN_THRESHOLD]
    flags = []
    for _,t in large.iterrows():
        flags.append(RuleFlag(
            rule="LARGE_TRANSACTION",
            detail=f"Transaction {t['transaction_id']} of {t['amount']} {t['currency']} exceeds ${LARGE_TXN_THRESHOLD:,} threshold.",
        ))
    return flags


def _flag_velocity(txns: pd.DataFrame) -> list[RuleFlag]:
    flags = []
    if txns.empty:
        return flags
    ts = txns.sort_values("timestamp")
    timestamps = pd.to_datetime(ts["timestamp"])
    window = timedelta(hours=VELOCITY_WINDOW_HOURS)

    for i in range(len(timestamps)):
        start = timestamps.iloc[i]
        count = ((timestamps >= start) & (timestamps < start + window)).sum()
        if count > VELOCITY_COUNT_THRESHOLD:
            flags.append(RuleFlag(
                rule="VELOCITY",
                detail=f"{count} transactions detected within a {VELOCITY_WINDOW_HOURS}-hour window starting {start}.",
            ))
            break  # one flag is enough; avoid duplicate near-identical flags
    return flags


def _flag_cross_border_high_risk(txns: pd.DataFrame) -> list[RuleFlag]:
    flags = []
    for _, t in txns.iterrows():
        sender = str(t.get("sender_country") or "").strip().lower()
        receiver = str(t.get("receiver_country") or "").strip().lower()
        if sender in HIGH_RISK_COUNTRIES or receiver in HIGH_RISK_COUNTRIES:
            flags.append(RuleFlag(
                rule="HIGH_RISK_JURISDICTION",
                detail=(
                    f"Transaction {t['transaction_id']} involves high-risk jurisdiction "
                    f"(sender={t.get('sender_country')}, receiver={t.get('receiver_country')})."
                ),
            ))
    return flags


def _flag_structuring(txns: pd.DataFrame) -> list[RuleFlag]:
    flags = []
    structuring_txns = txns[
        (txns["amount"] >= STRUCTURING_LOW) & (txns["amount"] <= STRUCTURING_HIGH)
    ]
    if len(structuring_txns) >= 2:
        flags.append(RuleFlag(
            rule="STRUCTURING",
            detail=(
                f"{len(structuring_txns)} transactions between "
                f"${STRUCTURING_LOW:,} and ${STRUCTURING_HIGH:,} detected — "
                "possible structuring to avoid reporting thresholds."
            ),
        ))
    return flags


def run_rule_engine(txns: pd.DataFrame) -> list[RuleFlag]:
    """Run all deterministic rules against one customer's transactions."""
    flags: list[RuleFlag] = []
    flags.extend(_flag_large_transactions(txns))
    flags.extend(_flag_velocity(txns))
    flags.extend(_flag_cross_border_high_risk(txns))
    flags.extend(_flag_structuring(txns))
    return flags


# ---------------------------------------------------------------------
# Stage 2: Groq LLM policy reasoning
# ---------------------------------------------------------------------

def _get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY is not set in your .env file.")
    return Groq(api_key=api_key)


def _retrieve_policy_context(query: str, match_count: int = 5) -> str:
    """Best-effort retrieval of relevant policy chunks for LLM grounding.
    Returns an empty string if no policy documents have been uploaded yet.

    match_threshold is tuned to 0.12 (down from 0.2) and top_k to 5, matching
    the Policy Chatbot's retrieval settings in services/rag_chat.py so both
    call sites behave consistently.
    """
    client = get_supabase_client()
    try:
        query_embedding = embed_text(normalize_query(query))
        resp = client.rpc(
            "match_document_chunks",
            {"query_embedding": query_embedding, "match_threshold": 0.12, "match_count": match_count},
        ).execute()
        chunks = resp.data or []
    except Exception:
        chunks = []

    if not chunks:
        return "No specific policy excerpts were retrieved. Use general AML best practice."

    parts = []
    for i, c in enumerate(chunks):
        label = c.get("file_name") or "Policy document"
        if c.get("page_number"):
            label += f", p. {c['page_number']}"
        parts.append(f"[Excerpt {i+1}] ({label}) {c['content']}")
    return "\n\n".join(parts)


def evaluate_with_llm(evaluation: CustomerEvaluation) -> CustomerEvaluation:
    """Call Groq to assign a final risk level + reasoning for a flagged customer."""
    flags_summary = "; ".join(f"{f.rule}: {f.detail}" for f in evaluation.flags)
    query_for_policy = f"Risk handling policy for: {flags_summary}"
    policy_context = _retrieve_policy_context(query_for_policy)

    user_prompt = f"""Customer: {evaluation.full_name} ({evaluation.external_id})
Transaction count: {evaluation.transaction_count}
Total volume: {evaluation.total_volume:,.2f}

Rule-engine flags:
{flags_summary if flags_summary else "None"}

Relevant policy excerpts:
{policy_context}
"""

    client = _get_groq_client()
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": RISK_REASONING_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=400,
    )
    raw = completion.choices[0].message.content.strip()

    # Defensive JSON parsing (strip accidental markdown fences)
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(cleaned)
        evaluation.risk_level = parsed.get("risk_level", "MEDIUM").upper()
        evaluation.reasoning = parsed.get("reasoning", raw)
    except json.JSONDecodeError:
        # Fallback: keep raw text as reasoning, default to MEDIUM since it
        # was flagged but the model's response couldn't be parsed cleanly.
        evaluation.risk_level = "MEDIUM"
        evaluation.reasoning = f"(Unparsed model output) {raw}"

    if evaluation.risk_level not in {"HIGH", "MEDIUM", "LOW"}:
        evaluation.risk_level = "MEDIUM"

    return evaluation


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------

def run_full_evaluation() -> list[CustomerEvaluation]:
    """Evaluate every customer in the database and persist results.

    Returns the list of CustomerEvaluation objects for display in the UI.
    """
    client = get_supabase_client()

    customers_resp = client.table("customers").select("*").execute()
    customers = customers_resp.data

    txns_resp = client.table("transactions").select("*").execute()
    all_txns = pd.DataFrame(txns_resp.data)

    results: list[CustomerEvaluation] = []

    for cust in customers:
        cust_id = cust["id"]
        cust_txns = (
            all_txns[all_txns["customer_id"] == cust_id]
            if not all_txns.empty else pd.DataFrame()
        )

        evaluation = CustomerEvaluation(
            customer_id=cust_id,
            external_id=cust["external_id"],
            full_name=cust["full_name"],
            transaction_count=len(cust_txns),
            total_volume=float(cust_txns["amount"].sum()) if not cust_txns.empty else 0.0,
        )

        flags = run_rule_engine(cust_txns) if not cust_txns.empty else []
        evaluation.flags = flags

        if flags:
            evaluation = evaluate_with_llm(evaluation)
        # else: stays LOW with default reasoning

        # Persist risk_assessments log
        client.table("risk_assessments").insert({
            "customer_id": cust_id,
            "risk_level": evaluation.risk_level,
            "flags": [{"rule": f.rule, "detail": f.detail} for f in evaluation.flags],
            "reasoning": evaluation.reasoning,
        }).execute()

        # Update customer's current risk_level
        client.table("customers").update(
            {"risk_level": evaluation.risk_level}
        ).eq("id", cust_id).execute()

        results.append(evaluation)

    return results


def get_customer_summary_table() -> pd.DataFrame:
    """Build a summary using each customer's latest persisted assessment."""
    client = get_supabase_client()
    customers_resp = client.table("customers").select("*").execute()
    customers = pd.DataFrame(customers_resp.data)

    if customers.empty:
        return pd.DataFrame(columns=[
            "external_id", "full_name", "country", "risk_level",
            "transaction_count", "total_volume",
        ])

    assessments_resp = (
        client.table("risk_assessments")
        .select("customer_id, risk_level, evaluated_at")
        .order("evaluated_at", desc=True)
        .execute()
    )
    assessments = pd.DataFrame(assessments_resp.data or [])
    if not assessments.empty:
        assessments = assessments.drop_duplicates("customer_id", keep="first")
        customers = customers.drop(columns=["risk_level"], errors="ignore").merge(
            assessments[["customer_id", "risk_level"]],
            left_on="id",
            right_on="customer_id",
            how="left",
        )
    customers["risk_level"] = customers["risk_level"].fillna("LOW")

    txns_resp = client.table("transactions").select("*").execute()
    txns = pd.DataFrame(txns_resp.data)

    if not txns.empty:
        agg = txns.groupby("customer_id").agg(
            transaction_count=("id", "count"),
            total_volume=("amount", "sum"),
        ).reset_index()
        merged = customers.merge(agg, left_on="id", right_on="customer_id", how="left")
    else:
        merged = customers.copy()
        merged["transaction_count"] = 0
        merged["total_volume"] = 0.0

    merged["transaction_count"] = merged["transaction_count"].fillna(0).astype(int)
    merged["total_volume"] = merged["total_volume"].fillna(0.0)

    return merged[[
        "external_id", "full_name", "country", "risk_level",
        "transaction_count", "total_volume",
    ]].sort_values("total_volume", ascending=False)


def get_latest_assessment_for_customer(customer_id: str) -> dict | None:
    client = get_supabase_client()
    resp = (
        client.table("risk_assessments")
        .select("*")
        .eq("customer_id", customer_id)
        .order("evaluated_at", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_customer_audit_details(customer_id: str) -> tuple[dict | None, pd.DataFrame]:
    """Return the latest assessment and transaction history for one customer."""
    client = get_supabase_client()
    assessment = get_latest_assessment_for_customer(customer_id)
    transactions_resp = (
        client.table("transactions")
        .select("*")
        .eq("customer_id", customer_id)
        .order("timestamp", desc=True)
        .execute()
    )
    return assessment, pd.DataFrame(transactions_resp.data or [])
