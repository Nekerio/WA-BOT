FROM python:3.12-slim
WORKDIR /app

# Buat user non-root untuk keamanan (Mencegah Privilege Escalation)
RUN addgroup --system appuser && adduser --system --group appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY .env .

# Ubah kepemilikan file aplikasi ke user non-root
RUN chown -R appuser:appuser /app

# Gunakan user non-root
USER appuser

# Jalankan Uvicorn dengan timeout-keep-alive untuk mitigasi serangan Slowloris
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "15"]
