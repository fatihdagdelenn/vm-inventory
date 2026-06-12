# ==========================================================
# VM Envanter Yönetim Sistemi - Uygulama imajı
# ==========================================================
FROM python:3.12-slim

# Sistem bağımlılıkları (psycopg2 ve cryptography için)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Önce bağımlılıkları kur (Docker katman önbelleği için ayrı adım)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodu
COPY app ./app

# Rapor ve SQLite verileri için dizin
RUN mkdir -p /app/data/reports

EXPOSE 8000

# Sağlık kontrolü: login sayfası yanıt veriyor mu?
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8000/login || exit 1

# Not: HTTPS için uvicorn'a --ssl-keyfile/--ssl-certfile verilebilir
# ya da önüne nginx/traefik reverse proxy konulabilir (önerilen).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
