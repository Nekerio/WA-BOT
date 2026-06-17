import time
import asyncio
import logging
import ipaddress
from collections import defaultdict
from fastapi import Request, Response, status

logger = logging.getLogger(__name__)

# Cache histori request untuk rate limiting (in-memory)
_rate_limit_history = defaultdict(list)

# Semaphore untuk membatasi task concurrent
SEMAPHORE_LIMIT = 20
task_semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)

# Referensi ke dictionary deduplikasi di main.py
_dedup_dict_ref = None

# Whitelist subnet IP terpercaya (localhost dan rentang IP Docker internal)
TRUSTED_SUBNETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("10.0.0.0/8"),
]

def set_dedup_dict_ref(dedup_dict: dict):
    """Menyimpan referensi dict deduplikasi dari main.py agar bisa dibersihkan berkala."""
    global _dedup_dict_ref
    _dedup_dict_ref = dedup_dict

def is_trusted_ip(client_ip: str) -> bool:
    """Memeriksa apakah client IP berasal dari host lokal atau subnet Docker internal."""
    try:
        # Jika client_ip berupa IPv6 loopback atau format tidak standar, sesuaikan
        if client_ip == "testclient" or client_ip == "localhost":
            return True
        ip = ipaddress.ip_address(client_ip)
        return any(ip in subnet for subnet in TRUSTED_SUBNETS)
    except ValueError:
        logger.warning(f"Format IP tidak valid untuk divalidasi: {client_ip}")
        return False

async def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """
    Melakukan pengecekan rate limit menggunakan algoritma Sliding Window.
    Mengembalikan True jika terkena rate limit (dibatasi), False jika aman.
    """
    now = time.time()
    timestamps = _rate_limit_history[key]
    
    # Filter hanya timestamp yang masih berada dalam window waktu
    active_timestamps = [t for t in timestamps if now - t < window_seconds]
    
    if len(active_timestamps) >= limit:
        return True
        
    active_timestamps.append(now)
    _rate_limit_history[key] = active_timestamps
    return False

async def periodic_cleanup_loop():
    """Loop background untuk membersihkan cache rate limiter dan deduplikasi secara berkala."""
    logger.info("Loop pembersihan berkala cache keamanan telah aktif.")
    while True:
        try:
            await asyncio.sleep(300)  # Berjalan setiap 5 menit
            now = time.time()
            
            # 1. Bersihkan histori rate limit yang sudah kedaluwarsa
            keys_to_delete = []
            for key, timestamps in list(_rate_limit_history.items()):
                # Simpan hanya timestamp dari 60 detik terakhir (window default)
                active = [t for t in timestamps if now - t < 60]
                if not active:
                    keys_to_delete.append(key)
                else:
                    _rate_limit_history[key] = active
            
            for key in keys_to_delete:
                _rate_limit_history.pop(key, None)
                
            # 2. Bersihkan cache deduplikasi pesan WhatsApp
            if _dedup_dict_ref is not None:
                dedup_keys_to_delete = []
                for key, timestamp in list(_dedup_dict_ref.items()):
                    # Hapus data yang usianya sudah lebih dari 60 detik (batas aman)
                    if now - timestamp > 60:
                        dedup_keys_to_delete.append(key)
                
                for key in dedup_keys_to_delete:
                    _dedup_dict_ref.pop(key, None)
            
            logger.info("Pembersihan berkala untuk cache rate-limiter dan deduplikasi selesai.")
        except Exception as e:
            logger.error(f"Terjadi kesalahan pada loop pembersihan berkala: {e}", exc_info=True)
