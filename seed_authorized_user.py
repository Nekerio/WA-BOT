import asyncio
import httpx
import uuid
from app.config import settings

async def seed_authorized_users():
    print("Mendaftarkan nomor telepon ke Supabase...")
    
    url = f"{settings.SUPABASE_URL}/rest/v1/authorized_users"
    headers = {
        "apikey": settings.SUPABASE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates" # Hindari error jika sudah ada
    }
    
    # Daftar nomor yang ingin didaftarkan (ganti dengan nomor Anda)
    phone_numbers = [
        "+6280000000000",
        "6280000000000",
        "6280000000000@c.us",
        "6280000000000@s.whatsapp.net",
        "264608757596404@lid" # Log test nomor dari WAHA
    ]
    
    for phone in phone_numbers:
        payload = {
            "id": str(uuid.uuid4()),
            "phone_number": phone
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code in [200, 201, 204]:
                    print(f"Sukses mendaftarkan: {phone}")
                elif response.status_code == 409:
                    print(f"Sudah terdaftar: {phone}")
                else:
                    print(f"Gagal mendaftarkan {phone}: {response.status_code}")
                    print(response.text)
            except Exception as e:
                print(f"Terjadi kesalahan untuk {phone}: {e}")

if __name__ == "__main__":
    asyncio.run(seed_authorized_users())
