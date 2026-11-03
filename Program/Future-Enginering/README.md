# Kedua jalur feature engineering IHSG

Folder ini hanya memuat kode pembentukan fitur dan modul yang diperlukan. Dataset dan direktori output tidak disertakan. Baca daftar prasyarat pada [README utama](../../README.md).

## Jalur 1: rebuild 15 fitur Inflation Change

Pintu masuk: `rebuild_inflation_change.py`.

Fitur X terdiri atas Return 1D, Return 5D, MA5, MA20, MA Ratio, Volatility 5D, Volatility 20D, RSI14, Volume Change, Foreign Net 5D, Return USD/IDR, Return Brent, US10Y Change, BI-Rate Change, dan Inflation Change antarrilis. Inflasi YoY mentah digunakan sebagai bahan perhitungan, bukan fitur langsung.

Modul pendukung: `feature_engineering.py`, `prepare_domestic15.py`, `prepare_inflation_release.py`, dan `build_targets.py`. Target lima hari dibentuk pada kalender penuh sebelum penyaringan baris complete.

Setelah input lokal lengkap, jalankan dari folder ini:

```bash
../Training/.venv/bin/python rebuild_inflation_change.py
```

Skrip membuat direktori baru dan mencetak lokasinya. Untuk sekaligus menjalankan training, gunakan `train_inflation_change.py` di folder Training.

## Jalur 2: delapan kandidat fitur

Pintu masuk: `rebuild_feature_candidates.py`. Jalur ini membaca baseline dari `output/inflation_change_rebuilt_20261028/` dan menggunakan helper audit BI dari folder Pre-Processing.

| Varian | Fitur | Perubahan |
|---|---:|---|
| `baseline_15` | 15 | Baseline Inflation Change |
| `without_volume_14` | 14 | Menghapus Volume Change |
| `relative_trend_15` | 15 | Mengganti MA5/MA20 dengan tren relatif |
| `risk_adjusted_16` | 16 | Menambahkan momentum yang dinormalisasi volatilitas |
| `foreign_pressure_17` | 17 | Menambahkan z-score foreign dan hitungan hari net buy |
| `domestic_policy_18` | 18 | Menambahkan perubahan BI 20/60 hari dan waktu sejak perubahan |
| `macro_5d_18` | 18 | Menambahkan perubahan makro lima hari |
| `combined_exploratory_24` | 24 | Menggabungkan tren relatif dan kelompok tambahan |

BI-Rate Change dan Inflation Change antarrilis tetap masuk seluruh varian. CSV gabungan memuat 26 fitur unik; model membaca whitelist fitur masing-masing varian. Target tetap lima hari perdagangan.

```bash
../Training/.venv/bin/python rebuild_feature_candidates.py
```

Gunakan lokasi output yang dicetak saat memanggil training kandidat. Semua tabel fitur, target, audit, dan metadata hasil eksekusi tetap lokal dan diabaikan Git. Jalur ini tidak mengubah model dashboard otomatis.
