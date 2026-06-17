import httpx
import logging
import urllib.parse
from app.config import settings

logger = logging.getLogger(__name__)

# Shared HTTP client — reuse koneksi TCP, lebih efisien
_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=60.0)
    return _client

def _waha_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "X-Api-Key": settings.WAHA_API_KEY
    }

async def send_message(session: str, chat_id: str, text: str):
    """Mengirim pesan teks balasan melalui WAHA API."""
    url = f"{settings.WAHA_URL}/api/sendText"
    payload = {
        "session": session,
        "chatId": chat_id,
        "text": text
    }
    
    client = _get_client()
    try:
        response = await client.post(url, json=payload, headers=_waha_headers())
        response.raise_for_status()
        logger.info(f"Pesan berhasil dikirim ke {chat_id}")
    except Exception as e:
        logger.error(f"Gagal mengirim pesan ke {chat_id}: {e}")

async def download_media(media_url: str, max_size_bytes: int = 10 * 1024 * 1024) -> bytes:
    """Mendownload file media (misal PDF) dari WAHA dengan batas ukuran (default 10MB)."""
    client = _get_client()
    try:
        content = bytearray()
        async with client.stream("GET", media_url, headers={"X-Api-Key": settings.WAHA_API_KEY}) as response:
            response.raise_for_status()
            
            # Periksa header Content-Length jika tersedia
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_size_bytes:
                raise ValueError(f"File berukuran {content_length} bytes, melebihi batas {max_size_bytes} bytes.")
                
            # Stream download chunk per chunk untuk mencegah bypass chunked encoding
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > max_size_bytes:
                    raise ValueError(f"Ukuran file streaming melebihi batas maksimal {max_size_bytes} bytes.")
                    
        return bytes(content)
    except Exception as e:
        logger.error(f"Gagal mendownload media dari {media_url}: {e}")
        raise e

async def is_saved_contact(session: str, chat_id: str) -> bool:
    """Mengecek apakah kontak terdaftar di daftar kontak WhatsApp melalui WAHA API."""
    url = f"{settings.WAHA_URL}/api/contacts?contactId={urllib.parse.quote(chat_id)}&session={session}"
    
    client = _get_client()
    try:
        response = await client.get(url, headers={"X-Api-Key": settings.WAHA_API_KEY})
        if response.status_code == 200:
            data = response.json()
            # 1. Cek isMyContact (jika didukung)
            is_my_contact = data.get("isMyContact")
            if is_my_contact is True:
                logger.info(f"Otorisasi kontak WAHA untuk {chat_id}: True (via isMyContact)")
                return True
                
            # 2. Fallback: Cek jika properti 'name' (nama kontak tersimpan) ada dan bernilai truthy
            contact_name = data.get("name")
            if contact_name:
                logger.info(f"Otorisasi kontak WAHA untuk {chat_id}: True (nama kontak: {contact_name})")
                return True
                
            logger.info(f"Otorisasi kontak WAHA untuk {chat_id}: False")
            return False
        else:
            logger.warning(f"Gagal mengambil info kontak {chat_id}: status {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Error pengecekan kontak WAHA untuk {chat_id}: {e}")
        return False

async def mark_read(session: str, chat_id: str):
    """Menandai semua pesan di chat tertentu sebagai telah dibaca (centang biru)."""
    url = f"{settings.WAHA_URL}/api/{session}/chats/{urllib.parse.quote(chat_id)}/messages/read"
    client = _get_client()
    try:
        response = await client.post(url, json={}, headers=_waha_headers())
        response.raise_for_status()
        logger.info(f"Chat {chat_id} berhasil ditandai sebagai dibaca.")
    except Exception as e:
        logger.error(f"Gagal menandai chat {chat_id} sebagai dibaca: {e}")

async def set_presence(session: str, chat_id: str, presence: str):
    """Mengatur status presence (typing, recording, paused) untuk chat tertentu."""
    url = f"{settings.WAHA_URL}/api/{session}/presence"
    payload = {
        "chatId": chat_id,
        "presence": presence
    }
    client = _get_client()
    try:
        response = await client.post(url, json=payload, headers=_waha_headers())
        response.raise_for_status()
        logger.info(f"Status presence '{presence}' berhasil dikirim ke {chat_id}")
    except Exception as e:
        logger.error(f"Gagal mengirim status presence '{presence}' ke {chat_id}: {e}")

async def get_phone_number_from_lid(session: str, lid: str) -> str | None:
    """Mendapatkan JID nomor telepon (@c.us) dari ID LID (@lid)."""
    encoded_lid = urllib.parse.quote(lid)
    url = f"{settings.WAHA_URL}/api/{session}/lids/{encoded_lid}"
    
    client = _get_client()
    try:
        response = await client.get(url, headers={"X-Api-Key": settings.WAHA_API_KEY})
        if response.status_code == 200:
            data = response.json()
            pn = data.get("pn")
            if pn:
                if not pn.endswith("@c.us"):
                    pn = f"{pn}@c.us"
                logger.info(f"Berhasil memetakan LID {lid} -> {pn}")
                return pn
        else:
            logger.warning(f"Gagal memetakan LID {lid}: status {response.status_code}")
    except Exception as e:
        logger.error(f"Error memetakan LID {lid}: {e}")
    return None


