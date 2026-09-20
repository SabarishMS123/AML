from database.supabase_client import get_supabase_client
client = get_supabase_client()

# Get all chunks from the policy document
chunks = client.table('document_chunks').select('id, content, page_number').execute()
print(f"=== All {len(chunks.data)} chunks ===")
for c in chunks.data:
    content = c['content']
    # Check for relevant terms
    if any(term in content.lower() for term in ['10,000', '10000', 'threshold', 'large transaction', 'large_transaction', 'high value', 'high-value']):
        print(f"\n[Page {c['page_number']}] {c['id'][:8]}... MATCHES:")
        print(content[:500])
        print("...")
    else:
        print(f"[Page {c['page_number']}] {c['id'][:8]}... {content[:80]}...")