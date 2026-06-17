import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)

# Shared HTTP client — reuse koneksi TCP
_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=60.0)
    return _client

def _supabase_headers(phone_number: str = "") -> dict:
    """Header standar Supabase — tidak perlu ditulis ulang di setiap fungsi."""
    headers = {
        "apikey": settings.SUPABASE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if phone_number:
        headers["X-Phone-Number"] = phone_number.strip()
    return headers

async def generate_embedding(text: str) -> list[float]:
    """Men-generate vektor embedding menggunakan Google Gemini API (gemini-embedding-2)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={settings.GEMINI_API_KEY}"
    payload = {
        "model": "models/gemini-embedding-2",
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": 768
    }
    
    client = _get_client()
    try:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()['embedding']['values']
    except Exception as e:
        logger.error(f"Gagal generate embedding untuk teks '{text}': {e}")
        raise e

async def is_phone_authorized(phone_number: str) -> bool:
    """Mengecek apakah nomor telepon terdaftar di Supabase (RLS)."""
    phone_clean = phone_number.strip()
    logger.info(f"Mengecek otorisasi RLS untuk nomor: {phone_clean}")
    try:
        url = f"{settings.SUPABASE_URL}/rest/v1/authorized_users?select=id&phone_number=eq.{phone_clean}"
        client = _get_client()
        response = await client.get(url, headers=_supabase_headers(phone_clean))
        response.raise_for_status()
        is_auth = len(response.json()) > 0
        logger.info(f"Hasil otorisasi untuk {phone_clean}: {is_auth}")
        return is_auth
    except Exception as e:
        logger.error(f"Error pengecekan RLS untuk nomor {phone_clean}: {e}")
        return False

async def search_obat(query: str, phone_number: str) -> list[dict]:
    """Mencari obat di Supabase menggunakan vector similarity search (RPC match_data_obat)."""
    logger.info(f"Mencari obat di database: {query} (Nomor: {phone_number})")
    try:
        embedding_vector = await generate_embedding(query)
        embedding_str = "[" + ",".join(map(str, embedding_vector)) + "]"
        
        url = f"{settings.SUPABASE_URL}/rest/v1/rpc/match_data_obat"
        payload = {
            "query_embedding": embedding_str,
            "match_threshold": 0.5,
            "match_count": 15
        }
        
        client = _get_client()
        response = await client.post(url, json=payload, headers=_supabase_headers(phone_number))
        response.raise_for_status()
        results = response.json()
        logger.info(f"Ditemukan {len(results)} hasil untuk pencarian '{query}'.")
        return results
    except Exception as e:
        logger.error(f"Gagal mencari obat di Supabase: {e}")
        return None

async def get_all_obat(phone_number: str) -> list[dict]:
    """Mengambil seluruh daftar obat dari tabel data_obat."""
    logger.info(f"Mengambil seluruh data obat dari Supabase (Nomor: {phone_number})")
    try:
        url = f"{settings.SUPABASE_URL}/rest/v1/data_obat?select=metadata"
        client = _get_client()
        response = await client.get(url, headers=_supabase_headers(phone_number))
        response.raise_for_status()
        results = response.json()
        logger.info(f"Berhasil mengambil {len(results)} obat dari database.")
        return results
    except Exception as e:
        logger.error(f"Gagal mengambil seluruh data obat di Supabase: {e}")
        return None

async def get_obat_perlu_restock(phone_number: str) -> list[dict]:
    """Mengambil data obat yang perlu direstock dari view view_obat_perlu_restock."""
    logger.info(f"Mengambil data obat perlu restock dari Supabase (Nomor: {phone_number})")
    try:
        url = f"{settings.SUPABASE_URL}/rest/v1/view_obat_perlu_restock?select=metadata"
        client = _get_client()
        response = await client.get(url, headers=_supabase_headers(phone_number))
        response.raise_for_status()
        results = response.json()
        logger.info(f"Berhasil mengambil {len(results)} obat perlu restock.")
        return results
    except Exception as e:
        logger.error(f"Gagal mengambil obat perlu restock di Supabase: {e}")
        return None

async def get_obat_dead_stock(phone_number: str) -> list[dict]:
    """Mengambil data obat dead stock dari view view_obat_dead_stock."""
    logger.info(f"Mengambil data obat dead stock dari Supabase (Nomor: {phone_number})")
    try:
        url = f"{settings.SUPABASE_URL}/rest/v1/view_obat_dead_stock?select=metadata"
        client = _get_client()
        response = await client.get(url, headers=_supabase_headers(phone_number))
        response.raise_for_status()
        results = response.json()
        logger.info(f"Berhasil mengambil {len(results)} obat dead stock.")
        return results
    except Exception as e:
        logger.error(f"Gagal mengambil obat dead stock di Supabase: {e}")
        return None

async def register_phone_number_variants(phone_input: str):
    """
    Membersihkan nomor telepon input dan mendaftarkan semua variasi formatnya
    agar cocok dengan otorisasi RLS.
    """
    phone_input = phone_input.strip()
    if not phone_input:
        raise ValueError("Nomor telepon kosong")
    
    client = _get_client()
    
    async def _register(phone: str):
        """Helper internal: upsert 1 nomor ke authorized_users."""
        url = f"{settings.SUPABASE_URL}/rest/v1/authorized_users?on_conflict=phone_number"
        headers = _supabase_headers()
        headers["Prefer"] = "resolution=merge-duplicates"
        try:
            response = await client.post(url, json={"phone_number": phone}, headers=headers)
            if response.status_code in [200, 201, 204]:
                logger.info(f"Nomor {phone} berhasil terdaftar di Supabase.")
            else:
                logger.warning(f"Gagal sinkronisasi nomor {phone}: status {response.status_code}")
        except Exception as e:
            logger.error(f"Error sinkronisasi nomor {phone}: {e}")

    # Kasus 1: Input sudah berupa JID (mengandung @)
    if "@" in phone_input:
        await _register(phone_input)
        await _register(phone_input.split("@")[0])
        return
    
    # Kasus 2: Input nomor telepon biasa
    clean_number = "".join(c for c in phone_input if c.isdigit())
    if not clean_number:
        raise ValueError("Nomor telepon tidak valid (tidak ada angka)")
    
    # Konversi ke format internasional 62...
    if clean_number.startswith("08"):
        clean_number = "628" + clean_number[2:]
    elif clean_number.startswith("8") and len(clean_number) >= 9:
        clean_number = "62" + clean_number
    
    for var in [clean_number, f"+{clean_number}", f"{clean_number}@c.us", f"{clean_number}@s.whatsapp.net"]:
        await _register(var)


class DuplicateObatError(ValueError):
    """Exception raised when trying to register a duplicate medicine."""
    pass

async def add_new_obat(nama: str, kekuatan: str, kandungan: str, tipe: str, fungsi: str, stok: int, harga: int, expired: str) -> bool:
    """Menambahkan obat baru ke database Supabase."""
    import uuid
    nama, kekuatan, kandungan = nama.strip(), kekuatan.strip(), kandungan.strip()
    tipe, fungsi, expired = tipe.strip(), fungsi.strip(), expired.strip()
    
    client = _get_client()
    
    # 0. Cek duplikat
    try:
        url_check = f"{settings.SUPABASE_URL}/rest/v1/data_obat?select=metadata"
        response_check = await client.get(url_check, headers=_supabase_headers())
        response_check.raise_for_status()
        for r in response_check.json():
            meta = r.get("metadata") or {}
            if meta.get("nama_obat", "").strip().lower() == nama.lower() and \
               meta.get("kekuatan_obat", "").strip().lower() == kekuatan.lower():
                logger.warning(f"Percobaan pendaftaran obat duplikat ditolak: {nama} {kekuatan}")
                raise DuplicateObatError(f"Obat {nama} {kekuatan} sudah terdaftar di database.")
    except (DuplicateObatError, ValueError):
        raise
    except Exception as e:
        logger.error(f"Gagal verifikasi duplikasi obat: {e}")
        raise e

    # 1. Generate embedding
    content = f"Nama Obat: {nama} | Kekuatan: {kekuatan} | Kandungan: {kandungan} | Tipe: {tipe} | Fungsi: {fungsi}"
    logger.info(f"Menambahkan obat baru: {nama} {kekuatan}")
    
    try:
        embedding_vector = await generate_embedding(content)
        embedding_str = "[" + ",".join(map(str, embedding_vector)) + "]"
        
        payload = {
            "id": str(uuid.uuid4()),
            "content": content,
            "metadata": {
                "nama_obat": nama, "kekuatan_obat": kekuatan,
                "kandungan": kandungan, "tipe": tipe, "fungsi": fungsi,
                "sisa_stok": int(stok), "harga": int(harga),
                "expired_date": expired, "lokasi_rak": "Rak A1"
            },
            "embedding": embedding_str
        }
        
        url = f"{settings.SUPABASE_URL}/rest/v1/data_obat"
        headers = _supabase_headers()
        headers["Prefer"] = "return=minimal"
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code in [200, 201, 204]:
            logger.info(f"Obat {nama} {kekuatan} berhasil ditambahkan ke Supabase.")
            return True
        else:
            logger.error(f"Gagal menambahkan obat: status {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Error saat menambahkan obat baru: {e}")
        return False

async def update_obat_field(nama_lengkap: str, field: str, value, operation: str = "set") -> bool:
    """
    Mengupdate field metadata obat (sisa_stok, harga, atau expired_date) berdasarkan nama lengkap.
    Mendukung operasi 'set', 'add', dan 'subtract' untuk angka.
    """
    ALLOWED_FIELDS = {"sisa_stok", "harga", "expired_date"}
    if field not in ALLOWED_FIELDS:
        logger.error(f"Akses ditolak: percobaan update field yang tidak diizinkan '{field}'")
        return False
        
    logger.info(f"Mencoba operasi '{operation}' pada {field} obat '{nama_lengkap}' dengan nilai {value}")
    try:
        url = f"{settings.SUPABASE_URL}/rest/v1/data_obat?select=id,metadata"
        client = _get_client()
        response = await client.get(url, headers=_supabase_headers())
        response.raise_for_status()
        
        # Cari obat yang cocok
        target_id, target_metadata = None, None
        for r in response.json():
            metadata = r.get("metadata", {}) or {}
            full_name = f"{metadata.get('nama_obat', '').strip()} {metadata.get('kekuatan_obat', '').strip()}".strip()
            if full_name.lower() == nama_lengkap.lower().strip():
                target_id = r.get("id")
                target_metadata = metadata
                break
        
        if not target_id:
            logger.warning(f"Obat '{nama_lengkap}' tidak ditemukan saat operasi {operation} pada {field}.")
            return False
        
        # Update field
        if field == "expired_date":
            target_metadata[field] = str(value)
        else:
            # Numerik
            val_int = int(value)
            if operation == "add":
                target_metadata[field] = target_metadata.get(field, 0) + val_int
            elif operation == "subtract":
                target_metadata[field] = max(0, target_metadata.get(field, 0) - val_int)
            else:
                target_metadata[field] = val_int
        
        url_patch = f"{settings.SUPABASE_URL}/rest/v1/data_obat?id=eq.{target_id}"
        headers = _supabase_headers()
        headers["Prefer"] = "return=minimal"
        response_patch = await client.patch(url_patch, json={"metadata": target_metadata}, headers=headers)
        if response_patch.status_code in [200, 201, 204]:
            logger.info(f"{field} obat '{nama_lengkap}' berhasil diperbarui. Nilai saat ini: {target_metadata[field]}")
            return True
        else:
            logger.error(f"Gagal PATCH update {field}: status {response_patch.status_code}")
            return False
    except Exception as e:
        logger.error(f"Error saat mengupdate {field} obat: {e}")
        return False
