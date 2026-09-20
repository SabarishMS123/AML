from database.supabase_client import get_supabase_client
from services.embeddings import embed_text
from utils.formatting import normalize_query

client = get_supabase_client()

# Simulate what the AML agent does for this customer
flags_summary = "LARGE_TRANSACTION: Transaction TXN-9006 of 250000.0 EUR exceeds $10,000 threshold."
query_for_policy = f"Risk handling policy for: {flags_summary}"

print(f"Query for policy: {query_for_policy}")
print(f"Normalized: {normalize_query(query_for_policy)}")

query_embedding = embed_text(normalize_query(query_for_policy))
print(f"Embedding length: {len(query_embedding)}")

resp = client.rpc(
    "match_document_chunks",
    {"query_embedding": query_embedding, "match_threshold": 0.12, "match_count": 5},
).execute()

chunks = resp.data or []
print(f"\n=== Retrieved {len(chunks)} chunks ===")
for i, c in enumerate(chunks):
    print(f"\n[Excerpt {i}] (similarity={c['similarity']:.4f}, page={c['page_number']}, file={c['file_name']})")
    print(c['content'][:300])
    print("...")