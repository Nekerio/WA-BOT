import logging
import asyncio
import re
import time
from fastapi import FastAPI, Request, BackgroundTasks
from app.waha_client import send_message, download_media, mark_read, set_presence, get_phone_number_from_lid
from app.pdf_handler import extract_text_from_pdf
from app.doc_handler import extract_text_from_doc
from app.ai_agent import chat

# Setup konfigurasi logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Menyimpan hash pesan terakhir untuk deduplikasi
last_processed_messages = {}

# Helper functions
def clean_input_val(val: str) -> str:
    return val.strip().strip("[]").strip()

def clean_expired_val(val: str) -> str:
    v = clean_input_val(val)
    if v.lower().startswith("expired "):
        v = v[8:].strip()
    return v.strip("[]").strip()

def clean_int_val(val: str) -> int:
    """Parsing angka dari input WhatsApp — titik sebagai separator ribuan."""
    v = clean_input_val(val).replace(".", "")
    digits = "".join(c for c in v if c.isdigit())
    if not digits:
        raise ValueError(f"Nilai '{val}' tidak mengandung angka yang valid.")
    return int(digits)

def clean_asterisks(text: str) -> str:
    """Hapus Markdown bold/italic yang tidak didukung WhatsApp."""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(?!\s)(.*?)(?<!\s)\*', r'\1', text)
    return text

def split_long_list_message(text: str, limit: int = 15) -> list[str]:
    """Membagi pesan berisi daftar obat panjang menjadi beberapa batch."""
    lines = text.split('\n')
    list_items = [(i, line) for i, line in enumerate(lines) if line.strip().startswith('-')]
    
    if len(list_items) <= limit:
        return [text]
    
    # Pisahkan intro (sebelum list pertama) dan outro (setelah list terakhir)
    intro = '\n'.join(lines[:list_items[0][0]]).strip()
    outro = '\n'.join(lines[list_items[-1][0] + 1:]).strip()
    all_items = [line for _, line in list_items]
    
    num_batches = (len(all_items) + limit - 1) // limit
    batches = []
    for i in range(num_batches):
        batch = '\n'.join(all_items[i * limit:(i + 1) * limit])
        if i == 0:
            prefix = f"{intro}\n" if intro else ""
            batches.append(f"{prefix}{batch}\n\n(Menampilkan bagian 1 dari {num_batches})")
        else:
            suffix = f"\n\n{outro}" if (i == num_batches - 1 and outro) else ""
            batches.append(f"Lanjutan daftar obat (Bagian {i + 1} dari {num_batches}):\n{batch}{suffix}")
    return batches


app = FastAPI(title="WAHA Bot Server")

async def initialize_waha_session():
    """Menginisialisasi sesi 'default' WAHA dengan NOWEB store enabled agar bisa memetakan LID."""
    from app.config import settings
    import httpx
    
    url_sessions = f"{settings.WAHA_URL}/api/sessions"
    headers = {
        "X-Api-Key": settings.WAHA_API_KEY,
        "Content-Type": "application/json"
    }
    
    # Retry loop untuk menunggu WAHA container siap sepenuhnya
    async with httpx.AsyncClient(timeout=30.0) as client:
        waha_ready = False
        response = None
        for attempt in range(15):  # Coba selama maksimal 45 detik (15 * 3 detik)
            try:
                logger.info(f"Mencoba menghubungi WAHA (percobaan ke-{attempt+1})...")
                response = await client.get(f"{url_sessions}/default", headers=headers)
                if response.status_code in (200, 404):
                    waha_ready = True
                    break
            except Exception:
                pass
            await asyncio.sleep(3.0)
            
        if not waha_ready or response is None:
            logger.error("Gagal menghubungi WAHA setelah beberapa percobaan. Inisialisasi dibatalkan.")
            return

        try:
            logger.info("Memeriksa konfigurasi sesi 'default'...")
            session_exists = (response.status_code == 200)
            
            payload = {
                "config": {
                    "noweb": {
                        "store": {
                            "enabled": True,
                            "fullSync": True
                        }
                    }
                }
            }

            if session_exists:
                default_session = response.json()
                config = default_session.get("config")
                
                # Cek jika store belum aktif (config null atau store enabled != True)
                if not config or not config.get("noweb", {}).get("store", {}).get("enabled"):
                    logger.info("Sesi 'default' terdeteksi tanpa NOWEB store. Memperbarui konfigurasi...")
                    # Update konfigurasi menggunakan PUT
                    put_resp = await client.put(f"{url_sessions}/default", json=payload, headers=headers)
                    logger.info(f"Pembaruan sesi 'default' respon: {put_resp.status_code}")
                    
                    # Restart sesi untuk menerapkan config baru
                    logger.info("Menghentikan sesi untuk menerapkan konfigurasi baru...")
                    await client.post(f"{url_sessions}/default/stop", headers=headers)
                    await asyncio.sleep(2.0)
                    
                    logger.info("Menjalankan sesi kembali...")
                    start_resp = await client.post(f"{url_sessions}/default/start", headers=headers)
                    logger.info(f"Menjalankan sesi 'default' respon: {start_resp.status_code}")
                else:
                    logger.info("Sesi 'default' dengan NOWEB store sudah terkonfigurasi dengan benar.")
                    
                    # Jika statusnya STOPPED, pastikan dijalankan
                    status = default_session.get("status")
                    if status == "STOPPED":
                        logger.info("Sesi 'default' terdeteksi mati. Menjalankan sesi...")
                        start_resp = await client.post(f"{url_sessions}/default/start", headers=headers)
                        logger.info(f"Menjalankan sesi 'default' respon: {start_resp.status_code}")
            else:
                # Jika belum ada sama sekali, buat baru dengan config lengkap
                logger.info("Sesi 'default' tidak ditemukan. Membuat sesi baru...")
                create_payload = {
                    "name": "default",
                    "config": {
                        "noweb": {
                            "store": {
                                "enabled": True,
                                "fullSync": True
                            }
                        }
                    }
                }
                create_resp = await client.post(url_sessions, json=create_payload, headers=headers)
                logger.info(f"Pembuatan sesi 'default' respon: {create_resp.status_code}")
                
                # Jeda 2 detik untuk menghindari race condition
                await asyncio.sleep(2.0)
                
                start_resp = await client.post(f"{url_sessions}/default/start", headers=headers)
                logger.info(f"Menjalankan sesi 'default' respon: {start_resp.status_code}")
                
        except Exception as e:
            logger.error(f"Gagal menginisialisasi sesi WAHA: {e}")



@app.on_event("startup")
async def startup_event():
    logger.info("Server Bot WhatsApp mulai berjalan. Menunggu webhook dari WAHA...")
    from app.security import set_dedup_dict_ref, periodic_cleanup_loop
    from app.scheduler import periodic_alarm_loop
    set_dedup_dict_ref(last_processed_messages)
    asyncio.create_task(periodic_cleanup_loop())
    asyncio.create_task(initialize_waha_session())
    asyncio.create_task(periodic_alarm_loop())

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Server berjalan normal"}

async def _process_message_inner(chat_id: str, body: str, has_media: bool, payload: dict, session: str):
    """Fungsi background untuk memproses pesan (download PDF, panggil AI, kirim balasan)."""
    try:
        # 1. Cek otorisasi (kontak WAHA + akses database Supabase)
        from app.waha_client import is_saved_contact
        from app.supabase_client import is_phone_authorized
        
        # Jika chat_id berformat LID (akhiran @lid), petakan dulu ke nomor telepon asli (@c.us)
        real_chat_id = chat_id
        if chat_id.endswith("@lid"):
            pn_chat_id = await get_phone_number_from_lid(session, chat_id)
            if pn_chat_id:
                real_chat_id = pn_chat_id
                logger.info(f"Menggunakan real_chat_id {real_chat_id} untuk otorisasi (LID asal: {chat_id})")
            else:
                logger.warning(f"Gagal memetakan LID {chat_id} ke nomor telepon. Menggunakan LID asal.")

        is_saved = await is_saved_contact(session, real_chat_id)
        if not is_saved:
            logger.warning(f"Akses ditolak. Nomor tidak disimpan di kontak WAHA: {real_chat_id} (LID: {chat_id}).")
            return
            
        has_db_access = await is_phone_authorized(real_chat_id)
        logger.info(f"Nomor {real_chat_id} memiliki akses database obat: {has_db_access}")

        # 2. Simulasi membaca pesan berdasarkan jumlah karakter pesan masuk
        # Base delay 1 detik + 0.01 detik per karakter pesan masuk (maksimal 4 detik)
        read_delay = min(4.0, 1.0 + len(body) * 0.01)
        logger.info(f"Simulasi membaca pesan dari {chat_id} selama {read_delay:.2f} detik...")
        await asyncio.sleep(read_delay)
        
        # Tandai pesan sebagai dibaca (centang biru)
        await mark_read(session=session, chat_id=chat_id)
        
        # Mulai status mengetik (typing)
        await set_presence(session=session, chat_id=chat_id, presence="typing")
        
        typing_start_time = time.time()
        
        try:
            # 3. Intersepsi Perintah /daftar
            msg_body = body.strip()
            if msg_body.lower().startswith("/daftar "):
                parts = msg_body.split()
                if len(parts) >= 3:
                    from app.config import settings
                    if parts[1] == settings.REGISTRATION_SECRET:
                        from app.supabase_client import register_phone_number_variants
                        try:
                            await register_phone_number_variants(parts[2])
                            await send_message(session=session, chat_id=chat_id,
                                text=f"[SUKSES] Nomor {parts[2]} berhasil didaftarkan untuk mendapatkan akses database obat.")
                        except Exception as e:
                            await send_message(session=session, chat_id=chat_id,
                                text=f"[GAGAL] Gagal mendaftarkan nomor: {str(e)}")
                    else:
                        await send_message(session=session, chat_id=chat_id,
                            text="[GAGAL] Token pendaftaran salah. Silakan periksa kembali token Anda.")
                else:
                    await send_message(session=session, chat_id=chat_id,
                        text="[INFORMASI] Format perintah salah. Gunakan format:\n`/daftar <token> <nomor_atau_JID>`")
                return

            # 4. Intersepsi Perintah /tambah_obat
            if msg_body.lower().startswith("/tambah_obat "):
                if not has_db_access:
                    await send_message(session=session, chat_id=chat_id,
                        text="[GAGAL] Anda tidak memiliki hak akses untuk memodifikasi database obat.")
                    return
                    
                content_part = msg_body[13:].strip()
                parts = [p.strip() for p in content_part.split("|")]
                if len(parts) >= 8:
                    try:
                        nama = clean_input_val(parts[0])
                        kekuatan = clean_input_val(parts[1])
                        kandungan = clean_input_val(parts[2])
                        tipe = clean_input_val(parts[3])
                        fungsi = clean_input_val(parts[4])
                        stok = clean_int_val(parts[5])
                        harga = clean_int_val(parts[6])
                        expired = clean_expired_val(parts[7])
                    except ValueError as ve:
                        await send_message(session=session, chat_id=chat_id,
                            text=f"[GAGAL] Format pengisian angka (Stok/Harga) tidak valid: {str(ve)}")
                        return

                    from app.supabase_client import add_new_obat, DuplicateObatError
                    try:
                        success = await add_new_obat(nama, kekuatan, kandungan, tipe, fungsi, stok, harga, expired)
                        if success:
                            await send_message(session=session, chat_id=chat_id,
                                text=f"[SUKSES] Obat {nama} {kekuatan} berhasil ditambahkan ke database apotek.")
                        else:
                            await send_message(session=session, chat_id=chat_id,
                                text=f"[GAGAL] Terjadi kesalahan saat menyimpan obat {nama} ke database.")
                    except DuplicateObatError:
                        await send_message(session=session, chat_id=chat_id,
                            text=f"[GAGAL] Obat {nama} {kekuatan} sudah terdaftar di database.")
                    except Exception as e:
                        await send_message(session=session, chat_id=chat_id,
                            text=f"[GAGAL] Gagal memproses data obat: {str(e)}")
                else:
                    await send_message(session=session, chat_id=chat_id,
                        text="[GAGAL] Format pengisian salah. Pastikan formatnya sesuai:\n`/tambah_obat Nama | Kekuatan | Kandungan | Tipe | Fungsi | Stok | Harga | Expired`")
                return

            # 5. Proses file dokumen (PDF/Word) jika ada
            pdf_text = None
            if has_media:
                media_info = payload.get("file") or payload.get("media") or {}
                media_url = media_info.get("url")
                mimetype = media_info.get("mimetype", "")
                filename = media_info.get("filename", "")
                
                if media_url and ("pdf" in mimetype.lower() or filename.lower().endswith(".pdf")):
                    logger.info(f"Mengunduh file PDF dari url: {media_url}")
                    pdf_bytes = await download_media(media_url)
                    pdf_text = extract_text_from_pdf(pdf_bytes)
                elif media_url and ("msword" in mimetype.lower() or "wordprocessingml" in mimetype.lower() or filename.lower().endswith((".docx", ".doc"))):
                    logger.info(f"Mengunduh file Word dari url: {media_url}")
                    doc_bytes = await download_media(media_url)
                    pdf_text = extract_text_from_doc(doc_bytes, filename)
                else:
                    logger.info(f"Media diabaikan (filename: {filename}, mimetype: {mimetype}), bukan PDF/Word.")
                    
            # 6. Serahkan ke AI Agent
            logger.info("Mengirim pesan ke AI Agent...")
            ai_response = await chat(user_message=body, chat_id=real_chat_id, pdf_text=pdf_text, has_db_access=has_db_access)
            
            # Tentukan target durasi mengetik berdasarkan jumlah karakter respon AI
            # Base delay 1.5 detik + 0.02 detik per karakter respon (maksimal 8 detik)
            target_typing_delay = min(8.0, 1.5 + len(ai_response) * 0.02)
            
            # 7. Parse dan eksekusi trigger update dari AI (unified regex)
            clean_ai_response = ai_response
            trigger_map = {
                "UPDATE_STOK_OBAT": ("sisa_stok", "STOK", "set"),
                "UPDATE_HARGA_OBAT": ("harga", "HARGA", "set"),
                "UPDATE_ED_OBAT": ("expired_date", "ED", "set"),
                "TAMBAH_STOK_OBAT": ("sisa_stok", "JUMLAH", "add"),
                "KURANGI_STOK_OBAT": ("sisa_stok", "JUMLAH", "subtract"),
            }
            
            for action_name, (db_field, value_label, operation) in trigger_map.items():
                pattern = rf"\[TINDAKAN:\s*{action_name}\s*\|\s*NAMA:\s*(.*?)\s*\|\s*{value_label}:\s*(.*?)\]"
                matches = re.finditer(pattern, clean_ai_response)
                for match in matches:
                    matched_str = match.group(0)
                    nama_obat = match.group(1).strip()
                    val = match.group(2).strip()
                    clean_ai_response = clean_ai_response.replace(matched_str, "").strip()
                    if has_db_access:
                        from app.supabase_client import update_obat_field
                        try:
                            await update_obat_field(nama_obat, db_field, val, operation=operation)
                        except Exception as e:
                            logger.error(f"Gagal update {db_field} via trigger {action_name}: {e}")

            # 8. Bersihkan format dan kirim balasan
            clean_response = re.sub(r"\[TINDAKAN:\s*KIRIM_PDF_SEMUA_OBAT\s*\|\s*FORMAT:\s*(.*?)\]", "", clean_ai_response).strip()
            cleaned_response = clean_asterisks(clean_response)
            
            # Hitung selisih waktu pengetikan yang sudah berjalan (proses AI + unduh PDF dll)
            elapsed_typing_time = time.time() - typing_start_time
            remaining_typing_delay = target_typing_delay - elapsed_typing_time
            
            if remaining_typing_delay > 0:
                logger.info(f"Melanjutkan status mengetik selama {remaining_typing_delay:.2f} detik agar lebih natural...")
                await asyncio.sleep(remaining_typing_delay)
                
            chat_bubbles = cleaned_response.split("[PISAH_PESAN]")
            is_first_bubble = True
            
            for bubble in chat_bubbles:
                bubble = bubble.strip()
                if not bubble:
                    continue
                    
                response_batches = split_long_list_message(bubble, limit=15)
                for j, batch_msg in enumerate(response_batches):
                    if not is_first_bubble or j > 0:
                        await asyncio.sleep(2.0)
                    await send_message(session=session, chat_id=chat_id, text=batch_msg)
                    is_first_bubble = False
                
        finally:
            # Hentikan status mengetik (paused)
            await set_presence(session=session, chat_id=chat_id, presence="paused")
            
    except Exception as e:
        logger.error(f"Terjadi kesalahan saat memproses pesan: {str(e)}", exc_info=True)

async def process_message(chat_id: str, body: str, has_media: bool, payload: dict, session: str):
    from app.security import task_semaphore
    async with task_semaphore:
        await _process_message_inner(chat_id, body, has_media, payload, session)


@app.post("/webhook/waha")
async def waha_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint utama untuk menerima webhook dari WAHA.
    Hanya merespon event 'message' yang dikirim dari user (bukan dari bot sendiri).
    """
    try:
        from app.security import is_trusted_ip, check_rate_limit
        from fastapi import HTTPException, status
        import json

        # 1. Validasi IP Pengirim Webhook
        client_ip = request.client.host if request.client else "unknown"
        if not is_trusted_ip(client_ip):
            logger.warning(f"Webhook ditolak dari IP tidak dikenal: {client_ip}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        # 2. Batasi Ukuran Payload Webhook (Maks 1MB) untuk cegah JSON Bomb
        body_bytes = await request.body()
        if len(body_bytes) > 1024 * 1024:
            logger.warning(f"Webhook ditolak karena ukuran terlalu besar: {len(body_bytes)} bytes")
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large")

        data = json.loads(body_bytes.decode("utf-8"))
        
        event = data.get("event")
        payload = data.get("payload", {})
        session = data.get("session", "default")
        
        if event != "message":
            return {"status": "ignored", "reason": "Bukan event message"}
            
        if payload.get("fromMe") is True:
            logger.info("Pesan dari diri sendiri diabaikan (mencegah loop 2x respon).")
            return {"status": "ignored", "reason": "Pesan dari bot sendiri"}
            
        chat_id = payload.get("from")
        body = payload.get("body") or ""
        has_media = bool(payload.get("hasMedia"))
        
        # 3. Validasi Panjang Pesan WhatsApp (Maks 5000 karakter)
        if len(body) > 5000:
            logger.warning(f"Pesan dari {chat_id} terlalu panjang ({len(body)} karakter). Mengabaikan pesan.")
            return {"status": "ignored", "reason": "Pesan melebihi batas 5000 karakter"}

        # 4. Rate Limiter per Nomor WhatsApp (30 request per menit)
        if await check_rate_limit(key=chat_id, limit=30, window_seconds=60):
            logger.warning(f"Rate limit tercapai untuk {chat_id}. Pesan diabaikan.")
            return {"status": "rate_limited", "reason": "Terlalu banyak pesan dalam 1 menit"}
        
        # Deduplikasi pesan dalam jarak 10 detik
        now = time.time()
        
        # Ekstrak ID pesan WAHA untuk akurasi deduplikasi
        msg_id = payload.get("id", "")
        if isinstance(msg_id, dict):
            msg_id = msg_id.get("_serialized", str(msg_id))
            
        # Jika msg_id tidak ada, gunakan filename media sebagai fallback
        media_info = payload.get("file") or payload.get("media") or {}
        media_url = media_info.get("url", "")
        
        dedup_key = f"{chat_id}_{body}_{msg_id}_{media_url}"
        
        if dedup_key in last_processed_messages and now - last_processed_messages[dedup_key] < 10:
            logger.info("Pesan duplikat diabaikan (mencegah respon dobel).")
            return {"status": "ignored", "reason": "Duplicate"}
        
        last_processed_messages[dedup_key] = now
        logger.info(f"Menerima pesan baru dari {chat_id}: '{body}' (Media: {has_media})")
        
        background_tasks.add_task(process_message, chat_id, body, has_media, payload, session)
        return {"status": "queued", "message": "Pesan sedang diproses di background"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Terjadi kesalahan di webhook: {str(e)}", exc_info=True)
        # Sembunyikan detail error dari HTTP response (Information Leakage Prevention)
        return {"status": "error", "message": "Terjadi kesalahan internal pada server"}
