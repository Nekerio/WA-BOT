import asyncio
import logging
from datetime import datetime, time, timedelta
import zoneinfo

from app.waha_client import send_message
from app.supabase_client import get_obat_perlu_restock

logger = logging.getLogger(__name__)

async def periodic_alarm_loop():
    logger.info("Alarm restock loop background task started.")
    import os
    target_phone = os.getenv("TARGET_PHONE", "6280000000000@c.us")
    
    # WIB Timezone (Asia/Jakarta)
    try:
        wib_tz = zoneinfo.ZoneInfo("Asia/Jakarta")
    except zoneinfo.ZoneInfoNotFoundError:
        from datetime import timezone
        wib_tz = timezone(timedelta(hours=7))

    target_time = time(hour=21, minute=0, second=0)
    
    while True:
        try:
            now = datetime.now(wib_tz)
            # Calculate next 21:00 WIB
            next_run = datetime.combine(now.date(), target_time, tzinfo=wib_tz)
            
            # If it's already past 21:00 today, schedule for 21:00 tomorrow
            if now >= next_run:
                next_run += timedelta(days=1)
                
            sleep_seconds = (next_run - now).total_seconds()
            logger.info(f"Alarm restock berikutnya dijadwalkan pada {next_run.strftime('%Y-%m-%d %H:%M:%S')} WIB (dalam {sleep_seconds:.0f} detik).")
                
            await asyncio.sleep(sleep_seconds)
            
            logger.info("Triggering restock alarm...")
            all_obat = await get_obat_perlu_restock(phone_number=target_phone)
            
            if all_obat is not None:
                if len(all_obat) > 0:
                    db_context_lines = []
                    for item in all_obat:
                        meta = item.get("metadata", {})
                        nama = meta.get("nama_obat", "")
                        kekuatan = meta.get("kekuatan_obat", "")
                        stok = meta.get("sisa_stok", 0)
                        ed = meta.get("expired_date", "")
                        
                        if stok <= 10:
                            icon = "🔴"
                        else:
                            icon = "🟡"
                            
                        db_context_lines.append(f"{icon} {nama} {kekuatan} (Stok: {stok} | ED: {ed})")
                        
                    db_context_text = "\n".join(db_context_lines)
                    
                    msg = (
                        "⏰ *ALARM RESTOCK APOTEK* ⏰\n\n"
                        "Ini adalah pengingat otomatis Anda setiap pukul 21:00 WIB.\n"
                        "Berikut daftar obat yang mendesak untuk di-restock atau mendekati ED hari ini:\n\n"
                        f"{db_context_text}\n\n"
                        "💡 _Segera jadwalkan pembelian agar stok tetap aman!_"
                    )
                else:
                    msg = (
                        "⏰ *ALARM RESTOCK APOTEK* ⏰\n\n"
                        "Kabar baik! Saat ini tidak ada obat yang menipis atau mendekati masa expired.\n"
                        "Stok apotek Anda dalam kondisi prima! ✨"
                    )
            else:
                msg = (
                    "⚠️ *ALARM RESTOCK APOTEK (GAGAL)* ⚠️\n\n"
                    "Sistem gagal memeriksa data stok karena terjadi gangguan koneksi ke database.\n"
                    "Silakan periksa koneksi internet server atau coba tanyakan secara manual."
                )
                
            await send_message(session="default", chat_id=target_phone, text=msg)
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error pada loop alarm: {e}")
            await asyncio.sleep(60)
