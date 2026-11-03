# Dashboard app EWS IHSG

Backend FastAPI/PostgreSQL dan frontend React/TypeScript/Vite untuk menampilkan regime IHSG, EWS, indikator, perbandingan model, riwayat, kalkulator Compoundly, dan kuesioner UAT. Folder `compoundly/` berisi kode frontend kalkulator yang dibangun oleh setup dashboard.

Dataset, model terlatih, database, jawaban UAT, kredensial admin, dan dependency terpasang tidak disertakan. Lengkapi prasyarat pada [README utama](../../README.md).

## Instalasi dan menjalankan

Sediakan Python yang kompatibel (environment penelitian menggunakan Python 3.13), Node.js/npm, dan PostgreSQL 16. Jalankan dari folder `Program/Dashboard`:

```bash
python3 setup.py
.venv/bin/python run.py
```

Setup memasang dependency Python pada environment dashboard dan membangun frontend utama serta Compoundly. Database lokal dibuat oleh launcher ketika belum tersedia; artefak penelitian tetap harus disediakan terpisah. Aplikasi dibuka pada `http://127.0.0.1:9000`. Tekan Ctrl+C untuk menghentikan proses.

Alternatif pada macOS: setelah setup selesai, klik dua kali `Mulai Dashboard.command`.

Jika port 9000 digunakan:

```bash
.venv/bin/python run.py --port 9001
```

Untuk memakai server PostgreSQL sendiri, atur environment `DATABASE_URL` sebelum startup. Tanpa pengaturan tersebut, launcher menggunakan PostgreSQL lokal khusus project pada port 55432.

## Artefak penelitian

Backend memakai baseline `Program/Training/runs/inflation_change_rebuilt_20261028/`, terutama `dashboard_models/`, `dashboard_final_test_20261028/`, dan direktori fitur/target yang cocok dengan metadata. Skrip pembentuk paket model dan evaluasi berada di folder Training. Semua artefak tersebut tidak disertakan dan tetap diabaikan Git.

Sebagian metadata menyimpan path absolut. Saat memindahkan project, rekonsiliasi lokasi dan bangun ulang metadata yang sesuai; menyalin source code saja belum cukup untuk menjalankan tampilan penelitian. Kode delapan kandidat fitur tidak otomatis mengganti baseline dashboard.

## Penggunaan lokal

Mode Penelitian membaca hasil tersimpan dan membedakan validation, final test, serta simulasi historis. Mode Live mengambil quote dan publikasi indikator melalui koneksi internet; feed dapat delayed dan sebagian seri merupakan proxy yang berbeda dari sumber penelitian.

Analisis admin UAT berada pada `/ngopiii`. Kredensial awal dibuat lokal di `.local/survey_admin_credentials.json`. Pengaturan khusus dapat menggunakan `SURVEY_ADMIN_USERNAME` dan `SURVEY_ADMIN_PASSWORD` secara bersamaan. Folder `.local/`, file `.env`, database, dan jawaban UAT tidak boleh disertakan ke repository.

Launcher berjalan lokal pada loopback. Publikasi source code ke GitHub tidak otomatis menjalankan atau men-deploy dashboard.
