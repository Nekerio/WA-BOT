import urllib.request
import json
import ssl
import time
import os
from dotenv import load_dotenv

load_dotenv()

# Credentials
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

def get_embedding(text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={GEMINI_API_KEY}"
    payload = {
        "model": "models/gemini-embedding-2",
        "content": {
            "parts": [{"text": text}]
        },
        "outputDimensionality": 768
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            return res_data['embedding']['values']
    except Exception as e:
        print(f"Error generating embedding for text '{text[:30]}...': {e}")
        return None

def main():
    print("Fetching records from Supabase...")
    # Fetch all records
    url_select = f"{SUPABASE_URL}/rest/v1/data_obat?select=id,content,embedding"
    req_select = urllib.request.Request(
        url_select,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }
    )
    
    try:
        with urllib.request.urlopen(req_select) as response:
            records = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print("Failed to fetch records:", e)
        return

    print(f"Total records found: {len(records)}")
    
    # Filter records that need embedding
    to_update = [r for r in records if r.get("embedding") is None]
    print(f"Records needing embedding: {len(to_update)}")
    
    if not to_update:
        print("All records already have embeddings!")
        return

    success_count = 0
    for i, r in enumerate(to_update):
        record_id = r['id']
        content = r['content']
        
        print(f"[{i+1}/{len(to_update)}] Processing ID: {record_id} ({content[:30]}...)")
        
        # Generate embedding
        vector = get_embedding(content)
        if vector is None:
            continue
            
        # Update in Supabase
        url_update = f"{SUPABASE_URL}/rest/v1/data_obat?id=eq.{record_id}"
        payload_update = {
            "embedding": vector
        }
        req_update = urllib.request.Request(
            url_update,
            data=json.dumps(payload_update).encode('utf-8'),
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            method="PATCH"
        )
        
        try:
            with urllib.request.urlopen(req_update) as response:
                success_count += 1
                print(f"  -> Successfully updated!")
        except Exception as e:
            print(f"  -> Failed to update record {record_id}: {e}")
            
        # Small delay to respect rate limit
        time.sleep(0.5)

    print(f"\nDone! Successfully updated {success_count}/{len(to_update)} records.")

if __name__ == "__main__":
    main()
