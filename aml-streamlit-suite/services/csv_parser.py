"""
services/csv_parser.py

Handles ingestion of transaction CSV files:
  - Parses with pandas
  - Upserts customer records
  - Batch-inserts transaction rows into Supabase

Expected CSV headers:
    customer_id, full_name, country, transaction_id, amount, currency,
    sender_country, receiver_country, timestamp, transaction_type
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

from database.supabase_client import get_supabase_client

REQUIRED_COLUMNS = [
    "customer_id", "full_name", "transaction_id", "amount", "timestamp",
]

OPTIONAL_COLUMNS_DEFAULTS = {
    "country": None,
    "currency": "USD",
    "sender_country": None,
    "receiver_country": None,
    "transaction_type": None,
}


@dataclass
class CsvIngestResult:
    num_customers_upserted: int
    num_transactions_inserted: int
    num_rows_skipped: int
    errors: list[str] = field(default_factory=list)


def read_transactions_csv(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(file_bytes))
    df.columns = [c.strip().lower() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    for col, default in OPTIONAL_COLUMNS_DEFAULTS.items():
        if col not in df.columns:
            df[col] = default

    return df


def ingest_transactions_csv(file_bytes: bytes) -> CsvIngestResult:
    client = get_supabase_client()
    df = read_transactions_csv(file_bytes)

    errors: list[str] = []
    num_rows_skipped = 0

    # --- 1. Upsert unique customers ---
    customers_df = (
        df[["customer_id", "full_name", "country"]]
        .drop_duplicates(subset=["customer_id"])
        .rename(columns={"customer_id": "external_id"})
    )

    customer_id_map: dict[str, str] = {}  # external_id -> internal UUID

    for _, row in customers_df.iterrows():
        external_id = str(row["external_id"])
        payload = {
            "external_id": external_id,
            "full_name": row["full_name"],
            "country": row["country"] if pd.notna(row["country"]) else None,
        }
        try:
            resp = (
                client.table("customers")
                .upsert(payload, on_conflict="external_id")
                .execute()
            )
            customer_id_map[external_id] = resp.data[0]["id"]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Customer {external_id}: {exc}")

    # For any customer not returned (upsert quirks on some client versions),
    # fetch back by external_id.
    missing_ids = [eid for eid in customer_id_map if not customer_id_map[eid]]
    if missing_ids:
        lookup = (
            client.table("customers")
            .select("id, external_id")
            .in_("external_id", missing_ids)
            .execute()
        )
        for r in lookup.data:
            customer_id_map[r["external_id"]] = r["id"]

    # --- 2. Build transaction rows ---
    transaction_rows = []
    for _, row in df.iterrows():
        external_id = str(row["customer_id"])
        internal_id = customer_id_map.get(external_id)
        if internal_id is None:
            num_rows_skipped += 1
            errors.append(f"Transaction {row['transaction_id']}: unresolved customer {external_id}")
            continue

        try:
            transaction_rows.append({
                "transaction_id": str(row["transaction_id"]),
                "customer_id": internal_id,
                "amount": float(row["amount"]),
                "currency": row["currency"] if pd.notna(row["currency"]) else "USD",
                "sender_country": row["sender_country"] if pd.notna(row["sender_country"]) else None,
                "receiver_country": row["receiver_country"] if pd.notna(row["receiver_country"]) else None,
                "timestamp": pd.to_datetime(row["timestamp"]).isoformat(),
                "transaction_type": row["transaction_type"] if pd.notna(row["transaction_type"]) else None,
            })
        except Exception as exc:  # noqa: BLE001
            num_rows_skipped += 1
            errors.append(f"Row for transaction {row.get('transaction_id')}: {exc}")

    # --- 3. Batch insert (upsert on transaction_id to allow re-uploads) ---
    num_inserted = 0
    BATCH = 200
    for i in range(0, len(transaction_rows), BATCH):
        batch = transaction_rows[i:i + BATCH]
        try:
            client.table("transactions").upsert(
                batch, on_conflict="transaction_id"
            ).execute()
            num_inserted += len(batch)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Batch insert error (rows {i}-{i+len(batch)}): {exc}")

    return CsvIngestResult(
        num_customers_upserted=len(customer_id_map),
        num_transactions_inserted=num_inserted,
        num_rows_skipped=num_rows_skipped,
        errors=errors,
    )

def delete_customer_by_external_id(external_id: str) -> bool:
    """Delete a single customer and all associated transactions and risk assessments."""
    client = get_supabase_client()
    
    # 1. Fetch internal customer UUID
    cust_resp = (
        client.table("customers")
        .select("id")
        .eq("external_id", external_id)
        .limit(1)
        .execute()
    )
    if not cust_resp.data:
        return False
        
    internal_id = cust_resp.data[0]["id"]

    # 2. Delete related records in dependent tables
    client.table("transactions").delete().eq("customer_id", internal_id).execute()
    client.table("risk_assessments").delete().eq("customer_id", internal_id).execute()

    # 3. Delete customer record
    client.table("customers").delete().eq("id", internal_id).execute()
    return True

def delete_all_customers_and_transactions() -> None:
    """Purge all customers, transaction logs, and risk assessments from Supabase."""
    client = get_supabase_client()
    dummy_uuid = "00000000-0000-0000-0000-000000000000"
    
    client.table("transactions").delete().neq("id", dummy_uuid).execute()
    client.table("risk_assessments").delete().neq("id", dummy_uuid).execute()
    client.table("customers").delete().neq("id", dummy_uuid).execute()