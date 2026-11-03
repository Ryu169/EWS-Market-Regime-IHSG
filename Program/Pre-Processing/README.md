# Helper preprocessing minimum

Folder ini hanya mempertahankan modul yang diperlukan oleh import kode kedua feature engineering:

- `apply_bi_rate_history.py`: pembaca riwayat dan identitas instrumen BI.
- `complete_gaps.py`: fungsi pendukung seri BIS yang diimpor pembaca BI.
- `preprocess_foreign.py`: helper checksum/pembacaan sumber yang diimpor modul lain.

Konfigurasi dan `requirements.txt` disertakan untuk mendukung modul tersebut. Pipeline preprocessing lengkap, dataset, workbook BI, manifest sumber, tabel audit, dan seluruh hasil preprocessing tidak disertakan. Sediakan input lokal sesuai [README utama](../../README.md).
