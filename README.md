# Catatan Kuliah

Aplikasi web catatan kuliah (Flask + PostgreSQL) yang dijalankan dengan Docker Compose di Azure VM.

## Menjalankan
```bash
cp .env.example .env      # isi DB_PASS
sudo docker compose up -d --build
sudo docker compose ps
```
Buka `http://<IP_PUBLIC_VM>`.

## Struktur
- `Dockerfile` - image aplikasi Flask
- `compose.yaml` - service `app` dan `db` (PostgreSQL), network internal, volume, healthcheck
- `.env.example` - contoh variabel rahasia (file `.env` tidak di-push)
