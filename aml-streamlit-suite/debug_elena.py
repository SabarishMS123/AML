from database.supabase_client import get_supabase_client
client = get_supabase_client()

# Check the specific customer (Elena Volkov)
cust_id = '5dbce7c0-1dbe-4265-8f06-2f6ea1bbf864'
cust = client.table('customers').select('*').eq('id', cust_id).execute()
print(f'=== Customer {cust_id} ===')
for c in cust.data:
    print(f"  {c['id']}: {c['external_id']} - {c['full_name']} - {c['country']} - {c['risk_level']}")

# Check risk assessment for this customer
assess = client.table('risk_assessments').select('*').eq('customer_id', cust_id).order('evaluated_at', desc=True).limit(1).execute()
print(f'\n=== Latest Risk Assessment ===')
if assess.data:
    a = assess.data[0]
    print(f"  risk_level: {a['risk_level']}")
    print(f"  flags: {a['flags']}")
    print(f"  reasoning: {a['reasoning']}")