"""Tahap 1: normalisasi dan left join Foreign ke tanggal IHSG, tanpa imputasi.

Membaca XLSX saja. Seluruh hasil ditulis sebagai CSV, JSON, dan Markdown.
"""
from __future__ import annotations

# 1. Pustaka yang dipakai untuk membaca konfigurasi, mengolah data, dan menulis hasil.
# Pustaka bawaan Python menangani CSV/JSON, tanggal, dan pemeriksaan berkas.
# openpyxl merupakan dependency tambahan untuk membaca workbook Excel.
import argparse
import csv
import hashlib
import json
import math
import platform
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import openpyxl

# 2. Konstanta bersama: lokasi skrip, nama kolom FNF, dan struktur laporan masalah.
# __file__ membuat lokasi default tidak bergantung pada folder terminal pengguna.
HERE = Path(__file__).resolve().parent
FNF = "foreign_net_flow_billion_idr"
# Kolom keluaran utama mengikuti urutan variabel yang diminta pengguna.
# Nama internal tetap dipakai di laporan agar arti satuan dan jejak sumber jelas.
OUTPUT_COLUMNS = {
    "Date": "date",
    "Open": "ihsg_open",
    "High": "ihsg_high",
    "Low": "ihsg_low",
    "Close": "ihsg_close",
    "Volume": "ihsg_volume_source",
    "Foreign": FNF,
}
ISSUE_FIELDS = ["dataset", "date", "field", "issue", "severity", "source_row", "value", "detail"]


def sha256(path):
    """Menghasilkan sidik jari isi berkas untuk mendeteksi perubahan sumber."""
    # Isi berkas yang sama akan menghasilkan checksum yang sama.
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_date(value, formats):
    """Menyeragamkan tanggal menjadi teks ISO YYYY-MM-DD sesuai format sumber."""
    # Excel dapat mengembalikan datetime meskipun sel hanya menampilkan tanggal.
    # Waktu selain tengah malam ditolak agar timestamp tidak dibuang diam-diam.
    if isinstance(value, datetime):
        if value.time().isoformat() != "00:00:00":
            raise ValueError(f"Tanggal mengandung waktu non-tengah-malam: {value}")
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # Tanggal berbentuk teks hanya dicoba dengan daftar format dari konfigurasi.
    # Contohnya 02/01/2026 dibaca sebagai 2 Januari bila formatnya %d/%m/%Y.
    if isinstance(value, str):
        for fmt in formats:
            try:
                return parse_date(datetime.strptime(value.strip(), fmt), formats)
            except ValueError:
                # Format ini tidak cocok; lanjut ke format berikutnya.
                continue
    # Jangan menebak tanggal yang gagal dibaca karena dapat salah menggabungkan data.
    raise ValueError(f"Tanggal tidak dikenali: {value!r}")


def parse_number(value, locale):
    """Membaca angka tanpa mengubah satuan atau mengisi nilai yang kosong."""
    # Penanda tidak tersedia menjadi None. Nilai nol asli tetap dibaca sebagai 0.
    if value is None or (isinstance(value, str) and value.strip() in {"", "-", "NA", "N/A", "null"}):
        return None
    # Python menganggap bool sebagai angka; cegah True/False masuk sebagai 1/0.
    if isinstance(value, bool):
        raise ValueError("Boolean tidak boleh menjadi nilai data")
    if isinstance(value, str):
        # Samakan karakter minus, kemudian baca format Indonesia secara eksplisit.
        # Contoh: teks -1.062,536 menjadi angka -1062.536.
        value = value.strip().replace("−", "-")
        if locale == "id_ID":
            if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", value):
                raise ValueError(f"Angka teks tidak sesuai locale id_ID: {value!r}")
            value = value.replace(".", "").replace(",", ".")
        else:
            raise ValueError(f"Locale angka teks belum didukung: {locale}")
    # Angka yang sejak awal numerik di Excel melewati konversi pemisah teks di atas.
    # NaN dan infinity ditolak karena bukan nilai observasi yang dapat dipakai.
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Nilai bukan angka finite: {value!r}")
    return number


def issue(issues, dataset, dt, field, code, detail, row="", value="", severity="warning"):
    """Menambahkan satu catatan kualitas dengan nama kolom laporan yang konsisten."""
    # zip memasangkan ISSUE_FIELDS dengan nilai catatan sesuai urutan yang sama.
    issues.append(dict(zip(ISSUE_FIELDS, [dataset, dt, field, code, severity, row, value, detail])))


def deduplicate(records, fields, dataset, issues):
    """Menghapus duplikat identik dan menolak nilai berbeda pada tanggal yang sama."""
    # Dictionary memakai tanggal sebagai kunci sehingga satu tanggal punya satu record.
    unique = {}
    duplicates = 0
    for record in records:
        dt = record["date"]
        if dt in unique:
            prior = unique[dt]
            # Bandingkan nilai data, bukan nomor baris Excel yang memang berbeda.
            # None dan 0 dianggap berbeda, jadi missing tidak disamakan dengan nol.
            if any(prior[f] != record[f] for f in fields):
                raise ValueError(f"{dataset}: duplikat bertentangan pada {dt}, baris {prior['source_row']} dan {record['source_row']}. Periksa sumber sebelum menjalankan ulang.")
            duplicates += 1
            issue(issues, dataset, dt, "date", "identical_duplicate_removed", "Duplikat identik; baris pertama dipertahankan.", record["source_row"])
        else:
            unique[dt] = record
    # Urutan ISO YYYY-MM-DD juga merupakan urutan tanggal secara kronologis.
    return sorted(unique.values(), key=lambda r: r["date"]), duplicates


def load_source(name, spec, config, base, issues):
    """Membaca satu workbook, menormalkan record, dan mencatat metadata sumber."""
    # Path relatif di konfigurasi dihitung dari folder konfigurasi, bukan folder terminal.
    path = (base / spec["path"]).resolve()
    before = sha256(path)
    # read_only mencegah penulisan melalui workbook ini dan menghemat memori.
    # data_only=False mempertahankan teks formula jika ada; parser tidak mengganti
    # formula dengan hasil cache yang mungkin sudah tidak sesuai isi workbook.
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = workbook[spec["sheet"]]
        iterator = sheet.iter_rows(values_only=True)
        # Lewati bagian atas sampai baris header yang ditentukan di konfigurasi.
        for _ in range(spec["header_row"]):
            header = next(iterator)
        required = [spec["date_header"], *spec["columns"]]
        # Setiap nama kolom harus ada tepat satu kali agar pemetaan tidak ambigu.
        for label in required:
            if header.count(label) != 1:
                raise ValueError(f"{name}: header {label!r} tidak ditemukan tepat satu kali")
        positions = {label: header.index(label) for label in required}
        records, blank_rows = [], 0
        # Nomor baris disimpan sesuai Excel (mulai 1), bukan indeks hasil yang mulai 0.
        for rownum, row in enumerate(iterator, start=spec["header_row"] + 1):
            # Baris kosong seluruhnya tidak mewakili observasi/tanggal yang hilang.
            if not any(v is not None and v != "" for v in row):
                blank_rows += 1
                continue
            # Ambil sel berdasarkan nama header; sel di ujung baris yang kosong
            # dapat tidak dikembalikan oleh pembaca, sehingga nilainya menjadi None.
            cell = lambda label: row[positions[label]] if positions[label] < len(row) else None
            try:
                record = {"date": parse_date(cell(spec["date_header"]), config["date_text_formats"]), "source_row": rownum}
                # Petakan label asli Excel ke nama kolom konsisten untuk analisis.
                for label, target in spec["columns"].items():
                    record[target] = parse_number(cell(label), config["numeric_text_locale"])
                records.append(record)
            except (ValueError, TypeError) as exc:
                # Sertakan baris sumber agar kesalahan parsing mudah ditelusuri.
                raise ValueError(f"{name}, baris Excel {rownum}: {exc}") from exc
    finally:
        # Tetap tutup workbook meskipun pembacaan atau parsing gagal.
        workbook.close()
    if not records:
        raise ValueError(f"{name}: tidak ada observasi")
    parsed_count = len(records)
    fields = list(spec["columns"].values())
    records, duplicates = deduplicate(records, fields, name, issues)
    # Pembacaan berhasil tidak membuktikan asal penyedia, satuan, atau waktu rilis.
    # Status yang belum terverifikasi dicatat, bukan diasumsikan sudah selesai.
    issue(issues, name, "", "source", "provenance_not_verified", "Berkas kompilasi pengguna; identitas penyedia per periode dan waktu ketersediaan belum diverifikasi.")
    issue(issues, name, "", "unit", "unit_requires_review", spec["unit_status"])
    # Metadata menghubungkan hasil bersih dengan berkas asli, sheet, dan checksum.
    meta = {"file": str(path), "sha256": before, "sheet": spec["sheet"], "header_row": spec["header_row"], "observation_rows": parsed_count, "blank_rows_skipped": blank_rows, "identical_duplicates_removed": duplicates, "unique_dates": len(records), "date_start": records[0]["date"], "date_end": records[-1]["date"], "missing_by_field": {f: sum(r[f] is None for r in records) for f in fields}, "unit_status": spec["unit_status"]}
    return records, meta


def validate_sources(ihsg, foreign, issues):
    """Mencatat masalah nilai IHSG/Foreign tanpa mengganti nilai sumber."""
    # Harga IHSG harus positif. Volume boleh nol, tetapi perlu pemeriksaan lanjutan.
    # severity='error' di laporan menandai masalah; fungsi ini tetap menyimpan data
    # agar pengguna dapat memeriksanya. Ini berbeda dari parsing gagal yang berhenti.
    for r in ihsg:
        dt, row = r["date"], r["source_row"]
        for field in ("ihsg_open", "ihsg_high", "ihsg_low", "ihsg_close", "ihsg_volume_source"):
            v = r[field]
            if v is None:
                issue(issues, "ihsg", dt, field, "missing_value", "Nilai kosong dipertahankan.", row)
            elif v < 0 or (field != "ihsg_volume_source" and v == 0):
                issue(issues, "ihsg", dt, field, "invalid_numeric_value", "Harga harus positif dan volume tidak boleh negatif; nilai sumber tetap disimpan.", row, v, "error")
        if r["ihsg_volume_source"] == 0:
            issue(issues, "ihsg", dt, "ihsg_volume_source", "zero_volume_requires_review", "Periksa sumber dan status hari perdagangan; nol tidak otomatis diganti atau diimputasi.", row, 0)
        # Open dan Close seharusnya berada dalam Low–High pada tanggal yang sama.
        # Toleransi 0,01 mengakomodasi perbedaan pembulatan kecil.
        lo, hi = r["ihsg_low"], r["ihsg_high"]
        if lo is not None and hi is not None:
            for field in ("ihsg_open", "ihsg_close"):
                v = r[field]
                if lo > hi or (v is not None and not lo - 0.01 <= v <= hi + 0.01):
                    issue(issues, "ihsg", dt, field, "ohlc_inconsistent", "Harga berada di luar rentang Low–High atau Low melebihi High (toleransi 0,01).", row, v, "error")
    # FNF negatif adalah net sell yang sah. Hanya nilai kosong yang dicatat di sini.
    for r in foreign:
        if r[FNF] is None:
            issue(issues, "foreign", r["date"], FNF, "missing_value", "FNF kosong tetap kosong; tidak diisi nol atau nilai sebelumnya.", r["source_row"])


def align(ihsg, foreign, issues):
    """Melakukan left join: semua tanggal IHSG dipertahankan, Foreign dicari per tanggal."""
    # Lookup berdasarkan tanggal mencegah salah pasang jika urutan sumber berbeda.
    by_date = {r["date"]: r for r in foreign}
    master_dates = {r["date"] for r in ihsg}
    joined = []
    for r in ihsg:
        f = by_date.get(r["date"])
        # Bedakan tanggal tidak ditemukan, baris ditemukan tetapi kosong, dan cocok.
        # Pemeriksaan 'is None' membuat nilai FNF nol tetap dianggap tersedia.
        status = "missing_date" if f is None else "missing_value" if f[FNF] is None else "matched"
        # Salin kolom IHSG, tambahkan FNF dan status, lalu beri nama khusus untuk
        # nomor baris kedua sumber agar nilai gabungan bisa dilacak kembali.
        joined.append({**{k: v for k, v in r.items() if k != "source_row"}, FNF: f[FNF] if f else None, "foreign_status": status, "ihsg_source_row": r["source_row"], "foreign_source_row": f["source_row"] if f else None})
        if status == "missing_date":
            issue(issues, "foreign", r["date"], "date", "missing_master_date", "Tanggal IHSG tidak ditemukan di Foreign; baris IHSG tetap dipertahankan.")
        if status != "matched" and r["ihsg_volume_source"] == 0:
            # Kombinasi ini menjadi alasan memeriksa kalender; belum membuktikan
            # bahwa tanggal tersebut harus dihapus dari hari perdagangan.
            issue(issues, "ihsg", r["date"], "date", "calendar_date_requires_review", "Volume nol bersamaan dengan FNF tidak tersedia; periksa bukti kalender perdagangan sebelum menghapus tanggal.", r["source_row"])
    # Tanggal tambahan tetap tersedia pada sumber bersih dan laporan terpisah.
    # Tanggal ini tidak digunakan untuk memperluas kalender master secara otomatis.
    extra = [r for r in foreign if r["date"] not in master_dates]
    for r in extra:
        issue(issues, "foreign", r["date"], "date", "outside_master_calendar", "Tidak ditambahkan ke kalender IHSG; nilai dan baris sumber disimpan pada laporan unmatched.", r["source_row"], r[FNF])
    return joined, extra


def write_csv(path, records, fields):
    """Menulis CSV dengan header, nilai kosong, dan encoding yang dapat dibaca Excel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Tulis ke berkas sementara dahulu agar target tidak berisi separuh CSV
    # apabila penulisan terhenti. Setelah selesai, ganti target dengan berkas ini.
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        # csv menulis None sebagai sel kosong. Nilai nol dan negatif tetap angka.
        writer.writerows(records)
    temporary.replace(path)


def run(config_path):
    """Menjalankan urutan pembacaan, pemeriksaan, penggabungan, dan penyimpanan."""
    # Tahap A: muat aturan serta tentukan folder keluaran data dan laporan.
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent
    output = base / config["output_dir"] / config["stage"]
    report = base / config["report_dir"] / config["stage"]
    issues = []
    # Tahap B: baca masing-masing sumber sebelum menggabungkan keduanya.
    ihsg, ihsg_meta = load_source("ihsg", config["ihsg"], config, base, issues)
    foreign, foreign_meta = load_source("foreign", config["foreign"], config, base, issues)
    # Tahap C: cek kewajaran nilai, kemudian selaraskan Foreign ke kalender IHSG.
    validate_sources(ihsg, foreign, issues)
    joined, extra = align(ihsg, foreign, issues)
    # Invarians integrasi: urutan, jumlah, dan nilai sumber tidak boleh berubah.
    if [r["date"] for r in joined] != [r["date"] for r in ihsg]:
        raise RuntimeError("Kalender IHSG berubah setelah join")
    # Cocokkan kembali FNF gabungan dengan sumber, termasuk None dan nilai negatif.
    source_foreign = {r["date"]: r[FNF] for r in foreign}
    for r in joined:
        if r[FNF] != source_foreign.get(r["date"]):
            raise RuntimeError("Nilai Foreign berubah setelah join")
    # Periksa apakah sumber berubah sejak awal pembacaan, misalnya sedang diedit
    # oleh aplikasi lain. Jika berubah, hentikan proses sebelum menulis hasil baru.
    for meta in (ihsg_meta, foreign_meta):
        if sha256(meta["file"]) != meta["sha256"]:
            raise RuntimeError("Berkas sumber berubah selama proses; jalankan ulang")
    # Tahap D: ekspor CSV dan simpan checksum hasil sebagai bukti pelaksanaan.
    artifacts = []
    def save_csv(path, records, fields):
        """Menyimpan satu CSV sekaligus mendaftarkannya ke metadata keluaran."""
        write_csv(path, records, fields)
        artifacts.append({"file": str(path.resolve()), "sha256": sha256(path), "rows": len(records)})
    ihsg_fields = ["date", *config["ihsg"]["columns"].values(), "source_row"]
    foreign_fields = ["date", FNF, "source_row"]
    # Sumber bersih tetap menyimpan seluruh tanggal masing-masing dataset.
    save_csv(output / "per_dataset/ihsg_clean.csv", ihsg, ihsg_fields)
    save_csv(output / "per_dataset/foreign_clean.csv", foreign, foreign_fields)
    save_csv(output / "calendar_ihsg.csv", [{"date": r["date"], "ihsg_source_row": r["source_row"]} for r in ihsg], ["date", "ihsg_source_row"])
    # Keluaran utama hanya berisi tujuh variabel. Nilai OHLCV tetap mengikuti
    # workbook IHSG; Foreign sudah dicocokkan berdasarkan tanggal oleh align().
    # Mengganti nama Volume tidak berarti mengesahkan satuan historisnya.
    main_rows = [{label: r[field] for label, field in OUTPUT_COLUMNS.items()} for r in joined]
    save_csv(output / "ihsg_foreign_aligned.csv", main_rows, list(OUTPUT_COLUMNS))
    # Status kualitas dan nomor baris kedua sumber ditempatkan di laporan audit.
    save_csv(report / "ihsg_foreign_alignment_audit.csv", joined, list(joined[0]))
    # Laporan detail memisahkan tanggal tambahan, FNF kosong, dan seluruh isu.
    save_csv(report / "foreign_unmatched_dates.csv", extra, foreign_fields)
    missing = [r for r in joined if r["foreign_status"] != "matched"]
    save_csv(report / "missing_foreign.csv", missing, list(joined[0]))
    save_csv(report / "quality_issues.csv", issues, ISSUE_FIELDS)
    # Tahap E: ringkas hasil pemeriksaan dalam JSON untuk dibaca program.
    # Counter menghitung banyaknya record untuk tiap status/kode masalah.
    counts = dict(Counter(r["foreign_status"] for r in joined))
    summary = {"stage": config["stage"], "status": "aligned_with_review_items", "model_ready": False, "calendar": "provided_ihsg_dates_not_independently_verified", "main_output_columns": list(OUTPUT_COLUMNS), "main_output_volume": "original_ihsg_workbook_values_unit_unverified", "main_output_foreign_unit": "billion_IDR_as_stated_in_source", "master_rows": len(ihsg), "foreign_rows": len(foreign), "foreign_status_counts": counts, "foreign_dates_outside_master": len(extra), "date_start": ihsg[0]["date"], "date_end": ihsg[-1]["date"], "zero_ihsg_volume_rows": sum(r["ihsg_volume_source"] == 0 for r in ihsg), "negative_foreign_values_retained": sum(r[FNF] is not None and r[FNF] < 0 for r in joined), "imputed_values": 0, "issue_counts": dict(Counter(i["issue"] for i in issues)), "sources": {"ihsg": ihsg_meta, "foreign": foreign_meta}}
    report.mkdir(parents=True, exist_ok=True)
    (report / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Ringkasan Markdown menjelaskan hasil dan batasannya dalam bahasa Indonesia.
    text = f"""# Pemeriksaan tahap 1: IHSG dan Foreign\n\nRentang tanggal: {summary['date_start']} sampai {summary['date_end']}.\n\n- Tanggal IHSG: {len(ihsg):,}.\n- Tanggal Foreign: {len(foreign):,}.\n- Foreign cocok dan bernilai: {counts.get('matched', 0):,}.\n- Tanggal master tanpa baris Foreign: {counts.get('missing_date', 0)}.\n- Baris Foreign pada master dengan nilai kosong: {counts.get('missing_value', 0)}.\n- Tanggal Foreign di luar master: {len(extra)}.\n- Volume IHSG nol: {summary['zero_ihsg_volume_rows']}.\n- Nilai Foreign negatif yang dipertahankan: {summary['negative_foreign_values_retained']:,}.\n- Nilai yang diimputasi: 0.\n\n## Keputusan pengolahan\n\nTanggal diambil dari berkas IHSG dan diurutkan. Penggabungan menggunakan left join berdasarkan tanggal dengan satu baris per tanggal. Tidak ada perluasan kalender, penambahan tanggal Foreign, atau penghapusan baris akibat data kosong. Duplikat identik dapat dibuang dengan catatan; duplikat bertentangan menghentikan proses.\n\nFNF sudah disediakan dalam miliar rupiah menurut catatan workbook. Nilainya diteruskan tanpa penghitungan ulang atau pembagian satu miliar. Nilai negatif merupakan net sell dan dipertahankan. Sel kosong tetap kosong. Tidak ada forward-fill, backward-fill, interpolasi, clipping, atau feature engineering.\n\n## Hal yang perlu diperiksa sebelum pemodelan\n\nSatuan Volume IHSG dan faktor konversi historis belum terbukti. Kolom `ihsg_volume_source` mempertahankan angka sumber tanpa konversi tambahan. Nilai nol perlu diperiksa sebelum perhitungan perubahan volume. Identitas penyedia, cakupan pasar, komponen beli/jual FNF, dan waktu ketersediaan belum diverifikasi dari berkas kompilasi ini.\n\nKalender mengikuti tanggal yang diberikan pengguna, belum diverifikasi secara mandiri terhadap kalender bursa. Tanggal dengan FNF kosong dan Volume nol ditandai untuk pemeriksaan kalender. Tanggal Foreign di luar master disimpan lengkap pada `foreign_unmatched_dates.csv`. Hasil tahap ini merupakan tabel penyelarasan untuk pemeriksaan, belum dataset siap pelatihan.\n\n## Jejak data\n\nHasil utama `ihsg_foreign_aligned.csv` berisi `Date, Open, High, Low, Close, Volume, Foreign`. OHLCV mempertahankan nilai workbook IHSG; penggantian nama Volume tidak mengesahkan satuannya. Tabel lengkap dengan status dan jejak sumber ada di `ihsg_foreign_alignment_audit.csv` pada folder laporan.\n\n`source_row`, `ihsg_source_row`, dan `foreign_source_row` menunjuk nomor baris Excel asli (mulai 1). Nama file, sheet, checksum SHA-256 dan rentang sumber tercatat pada `summary.json` serta `run_metadata.json`. Berkas sumber tidak ditulis ulang.\n"""
    (report / "summary.md").write_text(text, encoding="utf-8")
    # Tahap F: rekam versi Python/dependency, waktu UTC, konfigurasi, dan checksum.
    # model_ready tetap False: penyelarasan dua sumber belum menyelesaikan seluruh
    # validasi sumber, integrasi dataset lain, dan kebutuhan fitur model.
    metadata = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "python_version": platform.python_version(), "openpyxl_version": openpyxl.__version__, "script_sha256": sha256(__file__), "config_sha256": sha256(config_path), "config": config, "input_hashes_unchanged": True, "sources": summary["sources"], "artifacts": artifacts, "summary": {k: v for k, v in summary.items() if k != "sources"}}
    (report / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    """Menerima argumen terminal dan mengembalikan kode berhasil/gagal ke sistem."""
    # --config bersifat opsional; default-nya konfigurasi di sebelah skrip ini.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config_foreign.json")
    args = parser.parse_args()
    try:
        result = run(args.config)
    except (OSError, ValueError, KeyError, RuntimeError, StopIteration) as exc:
        # Pesan kegagalan ditulis ke stderr. Kode 1 menandakan proses tidak berhasil.
        print(f"GAGAL: {exc}. Hasil sukses sebelumnya (jika ada) tidak mewakili percobaan ini.", file=sys.stderr)
        return 1
    # Cetak angka ringkasan ke terminal; metadata sumber lengkap ada di laporan.
    print(json.dumps({k: v for k, v in result.items() if k != "sources"}, ensure_ascii=False, indent=2))
    return 0


# Jalankan main hanya saat berkas dieksekusi langsung, bukan saat diimpor pengujian.
if __name__ == "__main__":
    raise SystemExit(main())
