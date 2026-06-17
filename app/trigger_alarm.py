import asyncio
import logging
import zoneinfo
from datetime import datetime, timedelta

from app.waha_client import send_message
from app.supabase_client import get_obat_perlu_restock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def trigger_alarm():
    import os
    target_phone = os.getenv("TARGET_PHONE", "6280000000000@c.us")
    logger.info("Triggering restock alarm manually...")
    all_obat = await get_obat_perlu_restock(phone_number=target_phone)
    
    if all_obat is not None:
        if len(all_obat) > 0:
            db_context_lines = []
            for item in all_obat:
                meta = item.get("metadata", {})
                nama = meta.get("nama_obat", "")
                kekuatan = meta.get("kekuatan_obat", "")
                stok = meta.get("sisa_stok", "?")
                ed = meta.get("expired_date", "")
                
                try:
                    stok_val = int(stok)
                    is_low_stock = stok_val <= 10
                except:
                    is_low_stock = False
                    
                if is_low_stock:
                    icon = "🔴"
                else:
                    icon = "🟡"
                    
                db_context_lines.append(f"{icon} {nama} {kekuatan} (Stok: {stok} | ED: {ed})")
                
            db_context_text = "\n".join(db_context_lines)
            
            msg = (
                "⏰ *ALARM RESTOCK APOTEK (TEST)* ⏰\n\n"
                "Ini adalah pengingat manual Anda.\n"
                "Berikut daftar obat yang mendesak untuk di-restock atau mendekati ED hari ini:\n\n"
                f"{db_context_text}\n\n"
                f"*Total: {len(all_obat)} obat*\n\n"
                "💡 _Segera jadwalkan pembelian agar stok tetap aman!_"
            )
        else:
            msg = (
                "⏰ *ALARM RESTOCK APOTEK (TEST)* ⏰\n\n"
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

if __name__ == "__main__":
    asyncio.run(trigger_alarm())
