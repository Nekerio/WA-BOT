import asyncio
import csv
import json
import httpx
import os
import uuid
import random
from datetime import datetime, timedelta
from app.supabase_client import generate_embedding
from app.config import settings

async def seed_data():
    print("Membaca file seed_data.csv...")
    
    with open('seed_data.csv', 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        
        # URL Supabase REST API
        url = f"{settings.SUPABASE_URL}/rest/v1/data_obat"
        headers = {
            "apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        rows = []
        for i, row in enumerate(reader):
            if len(row) < 2:
                continue
                
            content = row[0]
            metadata_str = row[1]
            
            try:
                metadata = json.loads(metadata_str)
            except Exception as e:
                print(f"Error parsing json pada baris {i}: {e}")
                metadata = {"raw": metadata_str}
                
            # Tambahkan stok acak 1-100 dan expired date
            metadata['sisa_stok'] = random.randint(1, 100)
            metadata['harga'] = random.randint(5, 50) * 1000 # Harga 5.000 - 50.000
            metadata['lokasi_rak'] = f"Rak {random.choice(['A', 'B', 'C', 'D'])}{random.randint(1, 5)}"
            exp_date = datetime.now() + timedelta(days=random.randint(30, 1000))
            metadata['expired_date'] = exp_date.strftime("%Y-%m-%d")
            
            # Generate embedding
            print(f"Generating embedding untuk: {metadata.get('nama_obat')}...")
            try:
                embedding = await generate_embedding(content)
                embedding_str = "[" + ",".join(map(str, embedding)) + "]"
            except Exception as e:
                print(f"Gagal generate embedding: {e}")
                continue
                
            payload = {
                "id": str(uuid.uuid4()),
                "content": content,
                "metadata": metadata,
                "embedding": embedding_str
            }
            rows.append(payload)
            
        print(f"Berhasil memproses {len(rows)} baris. Memasukkan ke database...")
        
        # Insert ke Supabase
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=rows, headers=headers)
            
            if response.status_code in [200, 201, 204]:
                print(f"Sukses memasukkan {len(rows)} data obat ke Supabase!")
            else:
                print(f"Gagal insert ke Supabase: {response.status_code}")
                print(response.text)

if __name__ == "__main__":
    asyncio.run(seed_data())
