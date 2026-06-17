import fitz  # PyMuPDF
import logging

logger = logging.getLogger(__name__)

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Mengekstrak teks dari file PDF dalam bentuk bytes.
    Menggunakan pengelompokan berdasarkan koordinat vertikal (y0) agar tabel 
    terbaca per baris dari kiri ke kanan, bukan per kolom.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        full_text_lines = []
        
        for page in doc:
            words = page.get_text("words")
            # words adalah list dari (x0, y0, x1, y1, word, block_no, line_no, word_no)
            
            # Kelompokkan kata-kata dalam baris yang sama (toleransi vertikal 5 pixel)
            # Urutkan berdasarkan y0 (atas ke bawah), lalu x0 (kiri ke kanan)
            words.sort(key=lambda w: (round(w[1] / 5), w[0]))
            
            current_line = []
            current_y = -1
            
            for w in words:
                y = round(w[1] / 5)
                if current_y == -1:
                    current_y = y
                
                if abs(y - current_y) > 0:
                    full_text_lines.append(" ".join(current_line))
                    current_line = []
                    current_y = y
                    
                current_line.append(w[4])
                
            if current_line:
                full_text_lines.append(" ".join(current_line))
                
        result_text = "\n".join(full_text_lines)
        if not result_text.strip():
            return "[ERROR] PDF yang diunggah sepertinya berisi gambar atau hasil scan yang tidak memiliki teks yang bisa disorot. Harap unggah PDF dokumen teks."
            
        return result_text
    except Exception as e:
        logger.error(f"Gagal mengekstrak PDF: {e}")
        return f"[ERROR] Gagal membaca file PDF: {str(e)}"
