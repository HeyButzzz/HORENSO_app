# HORENSO — Problem Card System

Aplikasi web internal untuk pelaporan & manajemen masalah berbasis prinsip **HORENSO** (Hokoku - Renraku - Sodan), dilanjutkan dengan Action, Follow Up, Resolution, dan Closure.

**Stack:** Python + Flask, SQLite (via SQLAlchemy), server-rendered dengan Jinja2 + Tailwind CSS (CDN) + Alpine.js (CDN) untuk interaksi ringan. Tidak butuh Node.js atau proses build.

## Status prototipe

Ini adalah prototipe fase pertama yang mencakup alur inti end-to-end:

- Login / logout / lupa password (tautan reset ditampilkan langsung di layar — belum terhubung ke server email)
- Ganti password mandiri untuk setiap akun (password lama + password baru dua kali)
- Dashboard personal dengan ringkasan status, "Butuh Tindakan Anda", "Menunggu Keputusan", dan aktivitas terbaru
- Problem Card dengan 1 Problem = 1 Card, mencakup seluruh tab: Overview, HORENSO (Renraku & Sodan), Actions, Timeline, Lampiran
- Satu jalur pelaporan: wizard 3 langkah (Hokoku → Renraku → Sodan) — tidak ada jalur alternatif, sehingga setiap laporan lengkap dan seragam
- Assignment PIC, konsultasi & keputusan, action tracking, Resolution → Closure dua tahap, Root Cause Analysis opsional
- Permintaan tindakan berjenjang satu langkah: Senior → Supervisor → Asst. Manager → Manager, dengan opsi ambil alih atau kembalikan disertai arahan
- Ringkasan & pemetaan progres di paling atas menu laporan maupun di setiap Problem Card (tahapan HORENSO, tingkat penanganan, umur, dan status konfirmasi)
- Alur eskalasi berjenjang: User → Senior → Supervisor → Asst. Manager → Manager. Laporan selesai di tingkat mana pun; tingkat di atasnya cukup memberi konfirmasi "Mengetahui dan telah diselesaikan oleh PIC terkait"
- Deteksi masalah serupa/berulang (kategori + departemen yang sama dalam 30 hari terakhir)
- Notifikasi in-app, pencarian global, filter multi-kriteria, aging & SLA per prioritas
- RBAC 6 role (Admin, Manager, Asst. Manager, Supervisor, Senior, User/Reporter) dengan cakupan lihat & aksi terpisah per role
- Hapus akun dan hapus laporan (khusus Admin), keduanya dengan konfirmasi ketik-ulang dan penjagaan riwayat
- Kategori dilengkapi referensi cakupan bergaya jurnal pengujian, tampil sebagai panduan saat pelapor memilih kategori
- Admin Panel: Users, Departments, Categories, Priorities & SLA, Statuses, Theme/Branding, Audit Log
- Audit log menyeluruh: setiap perubahan di aplikasi tercatat — laporan, user, departemen, kategori, prioritas, status, branding, serta login/logout — lengkap dengan pelaku, alamat IP, dan waktu
- Logo & favicon diunggah sebagai file (bukan URL), dengan batas ukuran dan ukuran yang disarankan
- Seluruh tanggal & jam memakai waktu Indonesia Barat (WIB / Asia-Jakarta, GMT+7)
- CSRF protection, password hashing, validasi file upload
- Demo data siap pakai (10 user meliputi seluruh jenjang, 6 Problem Card contoh)

**Belum termasuk di fase ini** (menyusul di iterasi berikutnya): notifikasi email, live theme preview interaktif, aturan notifikasi yang bisa dikustomisasi granular, rate limiting login, analytics/grafik lanjutan (tren bulanan, waktu respons rata-rata), reminder due-date/overdue otomatis, dan manajemen status yang sepenuhnya dinamis (alur status saat ini masih mengikuti logika HORENSO yang sudah dikodekan, hanya label & warna yang bisa diubah dari Admin Panel).

## Menjalankan: cukup satu klik

Klik dua kali **`Start.bat`** di folder proyek. Skrip itu akan:

1. mencari Python di komputer Anda,
2. memasang dependencies bila belum ada (hanya saat pertama),
3. membuat database + data demo bila belum ada,
4. menjalankan server lalu membuka browser secara otomatis.

Tutup jendelanya (atau tekan `Ctrl+C`) untuk menghentikan server.

Server terikat ke seluruh interface, sehingga dapat diakses lewat
`http://10.10.20.19:8080` maupun `http://127.0.0.1:8080`. Jika IP tersebut
sedang tidak aktif di komputer itu, aplikasi tetap berjalan dan alamat lokal
yang dibuka.

Port dan alamat dapat diubah lewat environment variable `HORENSO_PORT` dan
`HORENSO_HOST` bila diperlukan.

## Zona waktu

Seluruh waktu yang ditampilkan maupun yang Anda ketik memakai **WIB (GMT+7)**.
Data disimpan dalam UTC dan dikonversi di dua tempat saja — saat ditampilkan dan
saat form dikirim — sehingga jam tetap benar meski server dipindah ke mesin
dengan zona waktu berbeda.

## Menjalankan secara manual

Proyek ini berada di folder `D:\Web App\HORENSU`.

### Cara tercepat: satu file `run.sh`

Cukup jalankan satu perintah ini (lewat Git Bash, WSL, atau terminal bash lainnya):

```bash
bash run.sh
```

Skrip ini otomatis: memeriksa & menginstal dependencies bila belum ada, membuat database + mengisi data demo saat pertama kali dijalankan, lalu menjalankan server. Setelah berjalan, buka **http://10.10.20.19:8080** di browser. Tekan `CTRL+C` di terminal untuk menghentikan server.

Untuk mengulang dari awal dengan database & data demo yang bersih:

```bash
bash run.sh --reset
```

Tidak punya bash di Windows? Install [Git for Windows](https://git-scm.com/downloads) (sudah termasuk Git Bash), lalu klik kanan folder proyek → "Git Bash Here" → jalankan `bash run.sh`.

### Cara manual (tanpa run.sh)

```bash
cd "D:\Web App\HORENSU"
pip install -r requirements.txt

# Buat database + isi data demo (sekali saja, atau setelah menghapus instance/horensu.db)
python seed.py

# Jalankan server
python run.py
```

Untuk mengulang dari awal dengan data demo yang bersih: `python seed.py --reset`.

Ingin mode auto-reload saat mengedit kode? Jalankan dengan `HORENSO_DEBUG=1 python run.py` (di Windows PowerShell: `$env:HORENSO_DEBUG=1; python run.py`).

## Permintaan tindakan berjenjang

Bila sebuah laporan di luar wewenang tingkat yang sedang menanganinya, tingkat
tersebut dapat **meminta tindakan ke satu tingkat di atasnya** — tidak boleh
melompat:

| Peminta | Tujuan |
|---------|--------|
| Senior | Supervisor |
| Supervisor | Asst. Manager |
| Asst. Manager | Manager |
| Manager | — (tingkat tertinggi) |

Penerima punya dua pilihan: **Ambil alih** (laporan berpindah menjadi tanggung
jawabnya) atau **Kembalikan** disertai arahan (wajib diisi). Selama satu
permintaan masih menunggu, permintaan baru tidak dapat dibuat. Seluruh
permintaan dan tanggapannya tercatat di Timeline dan Audit Log.

## Role & kewenangan

Laporan dari User masuk ke **Senior** terlebih dahulu. Bila Senior sudah dapat menyelesaikannya,
laporan dianggap selesai — tingkat di atasnya tidak mengerjakan ulang, cukup mencentang
*"Mengetahui dan telah diselesaikan oleh PIC terkait."* Aturan yang sama berlaku bila laporan
selesai di tingkat Supervisor: Asst. Manager dan Manager tinggal memberi konfirmasi.

| Role | Melihat laporan | Melakukan tindakan | Catatan |
|------|-----------------|--------------------|---------|
| **User / Reporter** | Hanya laporannya sendiri | — | Membuat laporan dan memantaunya |
| **Senior** | Departemennya sendiri | Departemennya sendiri | Tingkat pertama yang menerima laporan |
| **Supervisor** | Semua departemen | Hanya departemennya sendiri | Dapat memantau lintas departemen, tanpa hak aksi di luar departemennya |
| **Asst. Manager** | Semua departemen | Semua departemen | — |
| **Manager** | Semua departemen | Semua departemen | Puncak jenjang eskalasi |
| **Admin** | Semua departemen | Semua departemen | Satu-satunya role yang dapat menghapus akun dan laporan |

Bila sebuah departemen belum memiliki Senior aktif, laporan otomatis naik ke tingkat berikutnya
(Supervisor → Asst. Manager → Manager), dan jatuh ke Admin bila jenjangnya masih kosong — sehingga
laporan tidak pernah berhenti tanpa penerima.

## Akun demo

| Username | Password    | Role          | Departemen      |
|----------|-------------|---------------|-----------------|
| farhan   | farhan123   | Admin         | Quality Control |
| hendra   | horensu123  | Manager       | Quality Control |
| maya     | horensu123  | Asst. Manager | Quality Control |
| siti     | horensu123  | Supervisor    | Quality Control |
| budi     | horensu123  | Senior        | Quality Control |
| agus     | horensu123  | Supervisor    | Produksi        |
| joko     | horensu123  | Senior        | Produksi        |
| dedi     | horensu123  | Senior        | Maintenance     |
| rina     | horensu123  | User          | Produksi        |
| wati     | horensu123  | User          | Gudang          |

**Ganti seluruh password ini sebelum menggunakan aplikasi di luar demo internal.**

## Struktur proyek

```
HORENSU/            # nama folder di disk (aplikasi: HORENSO)
├── app/
│   ├── __init__.py        # App factory, error handlers, template helpers
│   ├── models.py          # Seluruh entity database (SQLAlchemy)
│   ├── timezone.py        # Konversi WIB (GMT+7) untuk tampilan & input form
│   ├── migrations.py      # Migrasi skema/data ringan, dijalankan otomatis saat app start
│   ├── auth.py            # Login, logout, lupa/reset password
│   ├── main.py             # Dashboard, notifikasi, pencarian global
│   ├── problems.py         # Problem Card: wizard, detail, actions, konsultasi, resolusi
│   ├── admin.py             # Admin panel (users, master data, tema, audit log)
│   ├── decorators.py        # RBAC helpers
│   ├── utils.py              # Kode Problem Card, notifikasi, upload file, deteksi duplikat
│   ├── templates/            # Jinja2 templates
│   └── static/                # CSS kustom & favicon
├── seed.py                    # Skrip data demo
├── run.py                      # Entry point
├── config.py                    # Konfigurasi (secret key, database, upload)
└── requirements.txt
```

## Konfigurasi produksi (sebelum dipakai sungguhan)

- Set environment variable `SECRET_KEY` ke nilai acak yang kuat (jangan pakai default di `config.py`)
- Pertimbangkan migrasi dari SQLite ke PostgreSQL untuk beban multi-user (ubah `DATABASE_URL`)
- Jalankan di belakang WSGI server produksi (mis. Waitress untuk Windows, atau Gunicorn di Linux), bukan `python run.py` langsung
- Aktifkan HTTPS dan `SESSION_COOKIE_SECURE=True`
- Sambungkan SMTP untuk notifikasi email (saat ini hanya in-app)
