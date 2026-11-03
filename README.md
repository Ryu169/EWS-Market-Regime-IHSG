# EWS Market Regime IHSG

Kode kedua jalur feature engineering, training terkait, dan dashboard app IHSG menggunakan XGBoost dan LightGBM.

## Cakupan repository

- **Feature engineering 1:** rebuild 15 fitur, termasuk BI-Rate Change dan Inflation Change antarrilis.
- **Feature engineering 2:** delapan varian kandidat fitur dengan populasi common complete.
- **Training:** runner kedua jalur, helper model/evaluasi, penyiapan model dashboard, dan evaluasi final test dashboard.
- **Dashboard app:** backend FastAPI/PostgreSQL, frontend React/TypeScript/Vite, dan kode kalkulator Compoundly.
- **Pendukung minimum:** tiga modul preprocessing yang diimpor oleh feature engineering beserta konfigurasi dan dependency terkait.

Dataset, model terlatih, prediksi per tanggal, hasil eksperimen tersimpan, database, kredensial, dan dependency yang sudah terpasang tidak disertakan. Eksperimen horizon 10/20 hari, revisi periode training 2024/2025, simulasi standalone, dan pipeline preprocessing lengkap tidak termasuk cakupan.

```text
Program/
├── Future-Enginering/   # Kedua jalur fitur dan helper-nya
├── Training/            # Training terkait dan paket model dashboard
├── Dashboard/           # Backend, frontend, dan Compoundly
└── Pre-Processing/      # Helper minimum yang diperlukan import fitur
```

Nama folder `Future-Enginering` dipertahankan agar path antarmodul tetap sesuai source code penelitian.

## Menyiapkan dependency

Dari root repository, gunakan Python yang kompatibel dengan dependency. Environment penelitian asal menggunakan Python 3.13.

```bash
python3 -m venv Program/Training/.venv
source Program/Training/.venv/bin/activate
python -m pip install -r Program/Training/requirements.txt -r Program/Pre-Processing/requirements.txt
```

Untuk dashboard diperlukan Node.js/npm dan PostgreSQL 16 atau database PostgreSQL yang ditentukan melalui `DATABASE_URL`. Petunjuk ada pada [README Dashboard](Program/Dashboard/README.md).

## Kedua jalur fitur dan training

| Jalur | Feature engineering | Training |
|---|---|---|
| Rebuild 15 fitur | `Program/Future-Enginering/rebuild_inflation_change.py` | `Program/Training/train_inflation_change.py` |
| Delapan kandidat | `Program/Future-Enginering/rebuild_feature_candidates.py` | `Program/Training/train_feature_candidates.py` |

Lihat [README Feature Engineering](Program/Future-Enginering/README.md) dan [README Training](Program/Training/README.md). Kode kandidat tidak otomatis mengganti model dashboard.

## Data dan artefak lokal yang diperlukan

Clone repository ini belum cukup untuk menjalankan penelitian secara penuh. Kode tetap memeriksa data historis, audit, checksum, threshold, fold, parameter, dan hasil referensi dari penelitian asal.

Input utama yang perlu disediakan secara lokal:

| Lokasi relatif | Fungsi |
|---|---|
| `Program/Pre-Processing/output/27_calendar_adjustments/ihsg_preprocessing_candidate.csv` | Preprocessing sumber |
| `Program/Pre-Processing/reports/27_calendar_adjustments/summary.json` | Laporan sumber/checksum |
| `Program/Pre-Processing/reports/10_bi_rate_history/bi_rate_daily_audit.csv` | Audit BI dan identitas instrumen |
| `Program/Pre-Processing/reports/06_dataset_candidate/availability_audit.csv` | Audit rilis inflasi |
| `Program/Pre-Processing/inputs/` dan `Program/Dataset/` | Sumber BI dan bukti pendukung lokal sesuai konfigurasi |
| `Program/Future-Enginering/output/ihsg_preprocessing_features_all.csv` | Pembanding sebelum koreksi sumber |
| `Program/Future-Enginering/output/domestic15_20261028_volume1111/targets/split_metadata.json` | Pembanding split historis |
| `Program/Future-Enginering/output/inflation_change_rebuilt_20261028/` | Baseline fitur, audit, dan target untuk kandidat |
| `Program/Training/runs/simple_retrain_20261026T201243_195442Z/summary.json` | Referensi parameter model tetap |
| `Program/Training/runs/inflation_release_20261028/<model>/change_15/result.json` | Metrik pembanding rebuild |
| `Program/Training/runs/inflation_change_rebuilt_20261028/` | Protokol baseline, model dashboard, dan evaluasi yang sesuai |

Tabel ini merangkum prasyarat utama; file sumber tambahan ditentukan oleh kode dan konfigurasi. Dataset baru atau metadata yang berbeda tidak otomatis kompatibel dengan pemeriksaan eksperimen historis. Sebagian metadata JSON menyimpan path absolut; pemulihan pada lokasi baru memerlukan rekonsiliasi path dan pembangunan ulang metadata melalui pipeline yang sesuai. Jangan menonaktifkan pemeriksaan atau membuat metrik/checksum buatan untuk melewati prasyarat.

Tiga helper preprocessing yang disertakan tidak membentuk pipeline preprocessing lengkap. Pengguna harus menyediakan keluaran preprocessing serta artefak referensi secara terpisah. Konfigurasi kolom, nama sumber, dan aturan koreksi dipertahankan sebagai bagian metode; file observasi tidak didistribusikan.

## Batas penggunaan

Kode berasal dari penelitian eksplorasi dengan catatan kualitas Volume, kalender, dan waktu tersedia makro. Validation dan final test harus dibaca terpisah. Instalasi dependency dan pemeriksaan sintaks tidak membuktikan reproduksi accuracy atau keberhasilan runtime tanpa data. `.gitignore` mengecualikan dataset, model, database, kredensial, dan hasil lokal.
