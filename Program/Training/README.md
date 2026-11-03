# Training terkait kedua jalur fitur dan dashboard

Dataset, artefak referensi, dan model tidak disertakan. Lengkapi prasyarat pada [README utama](../../README.md) sebelum menjalankan training. Semua perintah berikut dijalankan dari folder `Program/Training` setelah environment aktif.

```bash
source .venv/bin/activate
```

## Training rebuild 15 fitur

```bash
python train_inflation_change.py
```

Perintah ini menghitung ulang fitur dari preprocessing lalu melatih XGBoost dan LightGBM pada lima fold. Untuk menggunakan direktori fitur yang sudah tersedia:

```bash
python train_inflation_change.py --feature-dir ../Future-Enginering/output/NAMA_FOLDER_HASIL
```

Ganti `NAMA_FOLDER_HASIL` dengan direktori sebenarnya. Parameter tetap dibaca dari hasil eksperimen referensi lokal; metrik dibandingkan dengan hasil Inflation Change sebelumnya. File referensi tersebut harus tersedia agar pemeriksaan berhasil.

## Training delapan kandidat fitur

Periksa data terlebih dahulu, lalu lakukan training:

```bash
python train_feature_candidates.py --feature-dir ../Future-Enginering/output/NAMA_FOLDER_HASIL --check-data
python train_feature_candidates.py --feature-dir ../Future-Enginering/output/NAMA_FOLDER_HASIL
```

Konfigurasi default membandingkan delapan varian pada dua algoritma dan lima fold, yaitu 80 fit. Semua varian dibandingkan pada populasi common complete dan tanggal validation yang sama. Baseline lama dengan populasi berbeda tidak digunakan untuk menghitung kenaikan langsung. Protokol parameter default dibaca dari `runs/inflation_change_rebuilt_20261028/protocol.json`.

## Dukungan dashboard

- `prepare_dashboard_models.py`: refit dua model development dari hasil baseline yang sudah selesai dan membuat paket dashboard.
- `evaluate_dashboard_test.py`: mengevaluasi model beku pada final test.
- `train_models.py`, `train_domestic15.py`, dan `tune_models.py`: helper yang diimpor kedua runner dan skrip dashboard. Keberadaannya tidak berarti semua eksperimen lama dibagikan.

Model kandidat tidak otomatis menjadi model dashboard. Direktori fitur, hasil baseline, dan metadata dashboard harus konsisten. Hasil training baru disimpan lokal di `runs/` dan tidak ikut Git. Jangan menjalankan evaluasi atau refit hanya untuk melewati artefak yang belum tersedia.
