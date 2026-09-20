from database.supabase_client import get_supabase_client
import json
client = get_supabase_client()

cust_id = '5dbce7c0-1dbe-4265-8f06-2f6ea1bbf864'
assess = client.table('risk_assessments').select('*').eq('customer_id', cust_id).order('evaluated_at', desc=True).limit(1).execute()

with open('assessment_output.txt', 'w', encoding='utf-8') as f:
    if assess.data:
        a = assess.data[0]
        f.write(f"risk_level: {a['risk_level']}\n")
        f.write(f"flags: {json.dumps(a['flags'], indent=2)}\n")
        f.write(f"reasoning: {a['reasoning']}\n")
print("Written to assessment_output.txt")