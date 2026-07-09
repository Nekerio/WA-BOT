**INI ADALAH PROJECT 100% DIBUAT OLEH AI ANTIGRAVITY AKA GEMINI 3.1 PRO YANG SUDAH MELALUI PROSES REVISI. HAPPY TESTING** 

# WAHA + Supabase RAG Bot 🤖💊

Proyek ini adalah bot asisten WhatsApp pintar untuk apotek yang menggunakan pendekatan **RAG (Retrieval-Augmented Generation)**. Bot ini berjalan menggunakan **WAHA (WhatsApp HTTP API)** untuk integrasi WhatsApp, **Supabase dengan pgvector** untuk database pencarian stok obat berbasis vektor (semantic search), dan **Google Gemini / Claude (via KodeAPI)** sebagai kecerdasan buatan (LLM).

---

## 🚀 Fitur Utama
*   **Pencarian Vektor (Semantic Search)**: Mencari obat di database menggunakan kemiripan makna kata, bukan hanya kata kunci yang sama persis (misal: mencari "pusing" dapat memunculkan "Paracetamol").
*   **Dukungan Dokumen PDF**: Mengunggah PDF (berisi teks daftar obat) ke WhatsApp akan dibaca oleh bot, dicocokkan stoknya di database, dan dilaporkan statusnya.
*   **Deduplikasi Pesan**: Mencegah bot merespon dua kali jika menerima pesan ganda dalam waktu singkat.
*   **Penyimpanan Sesi WhatsApp**: Data login WhatsApp aman disimpan di dalam container volume sehingga tidak perlu scan QR Code berulang kali jika server restart.

---

## 📁 Struktur Proyek
```text
waha-bot-server/
├── app/
│   ├── __init__.py
│   ├── ai_agent.py          # Logika RAG & interaksi dengan LLM
│   ├── config.py            # Konfigurasi environment variables
│   ├── main.py              # Server FastAPI penerima webhook dari WAHA
│   ├── pdf_handler.py       # Pengekstrak teks dari dokumen PDF
│   ├── supabase_client.py   # Integrasi pencarian vektor ke Supabase
│   └── waha_client.py       # Client untuk mengirim pesan & download media dari WAHA
├── Dockerfile               # File docker untuk container bot Python
├── docker-compose.yaml      # Orkestrasi container WAHA dan Bot Server
├── .gitignore               # Mencegah file sensitif terunggah ke GitHub
├── .env.example             # Template file environment variabel untuk bot
├── .env.waha.example        # Template file environment variabel untuk WAHA
├── requirements.txt         # Ketergantungan pustaka Python
└── setup_supabase.sql       # Script SQL untuk fungsi pencarian di database Supabase
```

---

## 🛠️ Persiapan & Instalasi

### 1. Prasyarat
*   **Docker Desktop** sudah terinstal dan berjalan di komputer Anda.
*   Akun **Supabase** (proyek database PostgreSQL aktif).
*   **Gemini API Key** (untuk generate embedding teks).
*   **KodeAPI Key** (untuk pemrosesan LLM Claude Sonnet 4.6).

### 2. Setup Environment Variables
1. Salin file `.env.example` menjadi `.env` dan masukkan API Key Anda:
   ```bash
   cp .env.example .env
   ```
2. Salin file `.env.waha.example` menjadi `.env.waha` dan masukkan username/password dashboard WAHA Anda:
   ```bash
   cp .env.waha.example .env.waha
   ```

### 3. Setup Database Supabase
Buka **SQL Editor** di dashboard Supabase Anda dan jalankan perintah berikut:

```sql
-- 1. Aktifkan ekstensi pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Buat tabel data_obat
CREATE TABLE IF NOT EXISTS data_obat (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  content text,
  metadata jsonb,
  embedding vector(768) -- Menggunakan 768 dimensi (sesuai gemini-embedding-2)
);

-- 3. Buat indeks untuk kecepatan pencarian vektor
CREATE INDEX ON data_obat USING hnsw (embedding vector_cosine_ops);
```

Setelah tabel siap, jalankan script yang berada di file `setup_supabase.sql` untuk mendaftarkan fungsi RPC pencarian similarity vektor (`match_data_obat`).

---

## 🏃‍♂️ Menjalankan Aplikasi

Jalankan perintah berikut di terminal Anda pada direktori proyek:

```bash
docker compose up -d --build
```

Docker akan mengunduh image WAHA, membangun container Bot Server, dan menjalankannya di latar belakang.

*   **FastAPI Bot Server**: Berjalan di `http://localhost:8000` (Webhook URL: `/webhook/waha`).
*   **WAHA Dashboard**: Dapat diakses di `http://localhost:3000` (gunakan username & password dari file `.env.waha`).

---

## 🔒 Keamanan (Penting!)
Jangan pernah mengunggah file `.env` atau `.env.waha` ke GitHub karena berisi API Key rahasia Anda. File `.gitignore` dalam proyek ini sudah dikonfigurasi untuk mengecualikan kedua file tersebut agar tidak sengaja terunggah ke repositori publik.
