# VidiMatch Audit

Desktop app untuk audit kesamaan video dari link Shopee / TikTok / Instagram / Facebook.

## Format master Excel
Kolom wajib, huruf kecil:

| no | account | link |
|---|---|---|
| 1 | wida.08 | https://id.shp.ee/... |

## Cara Install Windows

1. Install Python 3.10+ dari https://python.org
2. Buka CMD di folder aplikasi ini
3. Jalankan:

```bash
pip install -r requirements.txt
playwright install chromium
```

4. Jalankan aplikasi:

```bash
python app.py
```

## Cara Pakai

1. Klik **Pilih Master Excel**
2. Pilih file `master.xlsx`
3. Jika punya cookie, klik **Tambah Cookie JSON**
4. Klik **Mulai Audit**
5. Setelah selesai, file hasil otomatis dibuat di folder yang sama dengan master Excel

## Output Excel

- no
- account
- link
- video identity
- persamaan video
- platform
- status

## Catatan

Aplikasi ini memakai metode cepat: mengambil final URL dan thumbnail metadata sebagai identitas video. Jika platform menyembunyikan data karena login, gunakan cookie JSON dari browser Anda sendiri.
