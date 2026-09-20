from database.supabase_client import get_supabase_client
client = get_supabase_client()

# Check policy documents
docs = client.table('policy_documents').select('*').execute()
print('=== Policy Documents ===')
for d in docs.data:
    print(f"  {d['id']}: {d['file_name']}")

# Check document chunks count
chunks = client.table('document_chunks').select('id, document_id, page_number, content').limit(10).execute()
print(f'\n=== Document Chunks (sample) ===')
for c in chunks.data:
    print(f"  chunk {c['id'][:8]}... doc={c['document_id'][:8]}... page={c['page_number']} content={c['content'][:80]}...")

# Check the specific customer
cust_id = '6131b27b-7572-4740-a287-4fde7cafd037'
cust = client.table('customers').select('*').eq('id', cust_id).execute()
print(f'\n=== Customer {cust_id} ===')
print(cust.data)

# Check their transactions
txns = client.table('transactions').select('*').eq('customer_id', cust_id).execute()
print(f'\n=== Transactions for customer ===')
for t in txns.data:
    print(f"  {t['transaction_id']}: {t['amount']} {t['currency']} {t['sender_country']}->{t['receiver_country']} type={t['transaction_type']}")

# Check risk assessment
assess = client.table('risk_assessments').select('*').eq('customer_id', cust_id).order('evaluated_at', desc=True).limit(1).execute()
print(f'\n=== Latest Risk Assessment ===')
if assess.data:
    a = assess.data[0]
    print(f"  risk_level: {a['risk_level']}")
    print(f"  flags: {a['flags']}")
    print(f"  reasoning: {a['reasoning']}")