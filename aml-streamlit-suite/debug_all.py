from database.supabase_client import get_supabase_client
client = get_supabase_client()

# Check all customers
custs = client.table('customers').select('*').execute()
print('=== All Customers ===')
for c in custs.data:
    print(f"  {c['id']}: {c['external_id']} - {c['full_name']} - {c['country']} - {c['risk_level']}")

# Check all transactions
txns = client.table('transactions').select('*').execute()
print(f'\n=== All Transactions ({len(txns.data)} total) ===')
for t in txns.data:
    print(f"  {t['transaction_id']}: cust={t['customer_id'][:8]}... {t['amount']} {t['currency']} {t['sender_country']}->{t['receiver_country']} type={t['transaction_type']}")

# Check risk assessments
assess = client.table('risk_assessments').select('*').execute()
print(f'\n=== All Risk Assessments ({len(assess.data)} total) ===')
for a in assess.data:
    print(f"  cust={a['customer_id'][:8]}... risk={a['risk_level']} flags={a['flags']}")
    print(f"    reasoning: {a['reasoning'][:120]}...")

# Search for TXN-9006
txn_9006 = client.table('transactions').select('*').eq('transaction_id', 'TXN-9006').execute()
print(f'\n=== TXN-9006 ===')
print(txn_9006.data)