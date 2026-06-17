-- 0. Praktik Keamanan Terbaik: Pastikan ekstensi vector ada di schema khusus
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector SCHEMA extensions;

-- Fungsi untuk melakukan pencarian vektor (vector similarity search)
-- pada tabel data_obat di Supabase.
-- Digunakan oleh server bot WhatsApp untuk mencari data obat.

CREATE OR REPLACE FUNCTION public.match_data_obat(
  query_embedding extensions.vector(768),
  match_threshold float DEFAULT 0.5,
  match_count int DEFAULT 15
)
RETURNS TABLE (
  id uuid,
  content text,
  metadata jsonb,
  similarity float
)
LANGUAGE plpgsql
-- Menetapkan search_path secara eksplisit untuk mencegah serangan pembajakan search path (Function Search Path Mutable)
SET search_path = public, extensions
AS $$
BEGIN
  RETURN QUERY
  SELECT
    data_obat.id,
    data_obat.content,
    data_obat.metadata,
    1 - (data_obat.embedding <=> query_embedding) AS similarity
  FROM public.data_obat
  WHERE 1 - (data_obat.embedding <=> query_embedding) > match_threshold
  ORDER BY data_obat.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- 1. Buat tabel authorized_users untuk menyimpan nomor telepon terdaftar
CREATE TABLE IF NOT EXISTS public.authorized_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Aktifkan Row Level Security (RLS) pada tabel
ALTER TABLE public.authorized_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_obat ENABLE ROW LEVEL SECURITY;

-- 3. Hapus policy lama jika ada
DROP POLICY IF EXISTS "Allow selection by authorized phone headers" ON public.data_obat;
DROP POLICY IF EXISTS "Allow selection by authorized phone headers" ON public.authorized_users;

-- 4. Buat policy RLS untuk tabel data_obat
-- Policy ini hanya memperbolehkan operasi SELECT jika nomor telepon pengirim 
-- (dikirim via header HTTP 'x-phone-number') ada di dalam tabel authorized_users.
CREATE POLICY "Allow selection by authorized phone headers" ON public.data_obat
FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM public.authorized_users
        WHERE public.authorized_users.phone_number = current_setting('request.headers', true)::json->>'x-phone-number'
    )
);

-- 5. Buat policy RLS untuk tabel authorized_users
-- Memungkinkan pengecekan apakah nomor pengirim terdaftar
CREATE POLICY "Allow selection by authorized phone headers" ON public.authorized_users
FOR SELECT
USING (
    phone_number = current_setting('request.headers', true)::json->>'x-phone-number'
);
