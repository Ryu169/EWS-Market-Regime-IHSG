"""Lengkapi BI Rate harian sambil menjaga rezim instrumen dan jejak sumber.

Membaca kandidat Volume tahap 09, workbook BI mentah, dan satu nilai awal BIS.
Keluaran berada di tahap 10; seluruh berkas sumber dan tahap 09 tetap utuh.
"""
from __future__ import annotations

import bisect
import csv
import json
from datetime import date, timedelta
from pathlib import Path

import openpyxl

from complete_gaps import bis_daily
from preprocess_foreign import sha256


HERE = Path(__file__).resolve().parent
INPUT = HERE.parent / "Dataset" / "BI Rate Jan 2008-Jul 2026.xlsx"
PREVIOUS = HERE / "output/09_idx_2020_recovery/ihsg_preprocessing_candidate.csv"
CONFIG = HERE / "config_all.json"
MANIFEST = HERE / "inputs/gap_sources_manifest.json"
CORRECTIONS = HERE / "inputs/bi_rate_policy_corrections.json"
OUTPUT_DIR = HERE / "output/10_bi_rate_history"
REPORT_DIR = HERE / "reports/10_bi_rate_history"
BI_PAGE = "https://www.bi.go.id/id/statistik/indikator/bi-rate.aspx"
BI_HISTORY = "https://www.bi.go.id/id/fungsi-utama/moneter/bi-rate/default.aspx"
POLICY_2016 = "https://www.bi.go.id/id/publikasi/ruang-media/news-release/Pages/sp_186716.aspx"
POLICY_2023 = "https://www.bi.go.id/id/publikasi/peraturan/Pages/PBI_152023.aspx"
MONTHS = {m: i for i, m in enumerate(
    "januari februari maret april mei juni juli agustus september oktober november desember".split(), 1)}
MAX_AGE_DAYS = 62


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def parse_rate(text: str) -> float:
    normalized = text.strip().replace("%", "").replace(" ", "").replace(",", ".")
    value = float(normalized)
    if not 0 <= value <= 100:
        raise ValueError(f"BI rate di luar rentang persen: {text!r}")
    return value


def parse_bi_date(text: str) -> str:
    day, month, year = text.strip().lower().split()
    return date(int(year), MONTHS[month], int(day)).isoformat()


def regime(observation_date: str) -> tuple[str, str]:
    # BI menyatakan pergantian 2023 hanya perubahan nama, bukan instrumen.
    if observation_date >= "2023-12-21":
        return "BI-Rate (nama baru untuk BI7DRR)", "reverse_repo_7_day"
    if observation_date >= "2016-08-19":
        return "BI 7-Day Reverse Repo Rate", "reverse_repo_7_day"
    return "BI Rate lama", "legacy_BI_Rate"


def load_bi_observations() -> tuple[list[dict], dict]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bi_spec = config["bi_rate"]
    if sha256(INPUT) != sha256((HERE / bi_spec["path"]).resolve()):
        raise ValueError("Path konfigurasi BI tidak menunjuk workbook mentah yang sama")

    workbook = openpyxl.load_workbook(INPUT, read_only=True, data_only=True)
    observations = []
    try:
        sheet = workbook[bi_spec["sheet"]]
        header = list(next(sheet.iter_rows(min_row=5, max_row=5, values_only=True)))
        if header != ["NO", "Tanggal", "BI-7Day-RR"]:
            raise ValueError(f"Header workbook BI berubah: {header}")
        for source_row, row in enumerate(sheet.iter_rows(min_row=6, values_only=True), 6):
            if not any(value is not None for value in row):
                continue
            if row[1] is None or row[2] is None:
                raise ValueError(f"Baris BI tidak lengkap: {source_row}")
            observations.append({
                "ObservationDate": parse_bi_date(str(row[1])),
                "BI_Rate": parse_rate(str(row[2])),
                "SourceRow": source_row,
                "SourceFile": str(INPUT),
                "SourceURL": BI_PAGE,
                "SourceType": "BI_indicator_workbook",
            })
    finally:
        workbook.close()

    observations.sort(key=lambda item: item["ObservationDate"])
    dates = [item["ObservationDate"] for item in observations]
    if len(dates) != 227 or len(dates) != len(set(dates)):
        raise ValueError(f"Jumlah/tanggal observasi BI tidak sesuai: {len(dates)}")
    if dates[0] != "2008-01-08" or dates[-1] != "2026-07-22":
        raise ValueError(f"Rentang data BI berubah: {dates[0]}–{dates[-1]}")

    # Sejak April 2016, BI mengumumkan BI7DRR berdampingan dengan BI Rate lama.
    # Workbook hanya menyimpan angka BI7DRR pada empat rapat sebelum tanggal
    # efektif. Ganti nilai kebijakan dengan angka pada siaran pers, tetapi
    # pertahankan WorkbookValue dan URL workbook pada audit.
    corrections_data = json.loads(CORRECTIONS.read_text(encoding="utf-8"))
    correction_map = {item["observation_date"]: item for item in corrections_data["evidence"]}
    if len(correction_map) != 4:
        raise ValueError("Daftar koreksi BI periode transisi tidak lengkap/duplikat")
    for item in observations:
        item["WorkbookValue"] = item["BI_Rate"]
        item["WorkbookSourceURL"] = item["SourceURL"]
        correction = correction_map.get(item["ObservationDate"])
        if correction:
            if item["BI_Rate"] != correction["workbook_value"]:
                raise ValueError(f"Nilai workbook BI pada {item['ObservationDate']} berubah")
            item["BI_Rate"] = correction["policy_rate_value"]
            item["SourceType"] = "official_BI_release_correction_to_parallel_7day_series"
            item["SourceURL"] = correction["press_release_url"]
            item["SourceTitle"] = correction["title"]
            item["WorkbookSeriesNote"] = "WorkbookValue adalah BI7DRR yang diumumkan paralel; BI Rate lama tetap menjadi kebijakan sampai 18 Agustus 2016."
        else:
            _, underlying = regime(item["ObservationDate"])
            item["SourceTitle"] = ""
            item["WorkbookSeriesNote"] = ""
            if item["ObservationDate"] < "2016-04-21":
                item["SourceType"] = "BI_indicator_workbook_legacy_policy_rate"
            elif item["ObservationDate"] >= "2016-08-19":
                item["SourceType"] = "BI_indicator_workbook_7day_policy_rate"
            else:
                raise ValueError(f"Observasi BI paralel yang belum dikoreksi: {item['ObservationDate']}")
        if item["ObservationDate"] in correction_map:
            correction_map.pop(item["ObservationDate"])
    if correction_map:
        raise ValueError(f"Koreksi tidak memiliki baris workbook: {sorted(correction_map)}")

    # Seri D:ID BIS bersumber Bank Indonesia dan memberi nilai yang telah ada
    # sebelum kalender IHSG dimulai; nilai sumber mentah tidak ditimpa.
    policy_source = manifest["sources"]["bis_policy"]
    bis_path = (HERE / policy_source["path"]).resolve()
    if sha256(bis_path) != policy_source["sha256"]:
        raise ValueError("Checksum sumber BIS kebijakan berubah")
    policy, source_row, metadata = bis_daily(bis_path, {"FREQ": "D", "REF_AREA": "ID"})
    if metadata.get("SOURCE_REF", "").strip() != "Bank Indonesia":
        raise ValueError("Sumber seri BIS kebijakan bukan Bank Indonesia")
    seed_date = config["gap_completion"]["bi_initial_observation_date"]
    seed = {
        "ObservationDate": seed_date,
        "BI_Rate": float(policy[seed_date]),
        "WorkbookValue": float(policy[seed_date]),
        "SourceRow": source_row,
        "SourceFile": str(bis_path),
        "SourceURL": policy_source["url"],
        "WorkbookSourceURL": policy_source["url"],
        "SourceType": "BIS_daily_series_sourced_from_BI_initial_history",
        "SourceTitle": "",
        "WorkbookSeriesNote": "",
    }
    if seed["BI_Rate"] != 8.0:
        raise ValueError(f"Nilai awal BI berubah dari pemeriksaan sumber: {seed['BI_Rate']}")
    observations.insert(0, seed)
    for item in observations:
        item["AvailableFrom"] = (date.fromisoformat(item["ObservationDate"]) + timedelta(days=1)).isoformat()
        item["BI_Instrument"] , item["UnderlyingRegime"] = regime(item["ObservationDate"])
    return observations, {"config": config, "policy_source": policy_source, "bis_path": bis_path,
                          "corrections_path": CORRECTIONS}


def main() -> None:
    input_hashes_before = {str(INPUT): sha256(INPUT), str(PREVIOUS): sha256(PREVIOUS)}
    rows, fields = read_csv(PREVIOUS)
    if len(rows) != 4500 or fields != ["Date", "Close", "Volume", "Foreign", "USD_IDR", "Brent", "US10Y", "BI_Rate", "Inflation_YoY"]:
        raise ValueError(f"Kandidat tahap 09 berubah: {len(rows)} baris; {fields}")
    if len({row["Date"] for row in rows}) != len(rows):
        raise ValueError("Tanggal IHSG duplikat pada kandidat tahap 09")

    observations, metadata = load_bi_observations()
    available = [item["AvailableFrom"] for item in observations]
    previous_bi = {row["Date"]: row["BI_Rate"] for row in rows}
    original_non_bi = {row["Date"]: {field: row[field] for field in fields if field != "BI_Rate"} for row in rows}
    daily_audit = []
    filled = 0
    for row in rows:
        index = bisect.bisect_right(available, row["Date"]) - 1
        if index < 0:
            event = None
            status = "no_available_observation"
        else:
            event = observations[index]
            age = (date.fromisoformat(row["Date"]) - date.fromisoformat(event["ObservationDate"])).days
            if age > MAX_AGE_DAYS:
                event = None
                status = "previous_observation_exceeds_maximum_age"
            else:
                status = "asof_source_observation"
        row["BI_Rate"] = "" if event is None else f"{event['BI_Rate']:g}"
        if previous_bi[row["Date"]] == "" and row["BI_Rate"] != "":
            filled += 1
        if previous_bi[row["Date"]] != "" and row["BI_Rate"] != "":
            if abs(float(previous_bi[row["Date"]]) - float(row["BI_Rate"])) > 1e-12:
                raise ValueError(f"Nilai BI modern berubah dibandingkan tahap 09 pada {row['Date']}")
        if {field: row[field] for field in fields if field != "BI_Rate"} != original_non_bi[row["Date"]]:
            raise ValueError(f"Kolom selain BI_Rate berubah pada {row['Date']}")
        daily_audit.append({
            "Date": row["Date"],
            "BI_Rate": row["BI_Rate"],
            "ObservationDate": event["ObservationDate"] if event else "",
            "AvailableFrom": event["AvailableFrom"] if event else "",
            "BI_Instrument": event["BI_Instrument"] if event else "",
            "UnderlyingRegime": event["UnderlyingRegime"] if event else "",
            "AgeCalendarDays": (date.fromisoformat(row["Date"]) - date.fromisoformat(event["ObservationDate"])).days if event else "",
            "Status": status,
            "SourceType": event["SourceType"] if event else "",
            "WorkbookValue": event["WorkbookValue"] if event else "",
            "WorkbookSourceURL": event["WorkbookSourceURL"] if event else "",
            "SourceTitle": event["SourceTitle"] if event else "",
            "SourceFile": event["SourceFile"] if event else "",
            "SourceRow": event["SourceRow"] if event else "",
            "SourceURL": event["SourceURL"] if event else "",
        })

    # Rekonsiliasi modern membuktikan aturan baru tidak mengubah stage 09.
    modern_rows = [item for item in daily_audit if item["UnderlyingRegime"] == "reverse_repo_7_day"]
    legacy_rows = [item for item in daily_audit if item["UnderlyingRegime"] == "legacy_BI_Rate"]
    missing_after = sum(not row["BI_Rate"] for row in rows)
    if missing_after:
        raise ValueError(f"BI masih kosong setelah penyelarasan: {missing_after}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    candidate_path = OUTPUT_DIR / "ihsg_preprocessing_candidate.csv"
    daily_audit_path = REPORT_DIR / "bi_rate_daily_audit.csv"
    observation_audit_path = REPORT_DIR / "bi_rate_observation_audit.csv"
    write_csv(candidate_path, rows, fields)
    audit_fields = ["Date", "BI_Rate", "ObservationDate", "AvailableFrom", "BI_Instrument",
                    "UnderlyingRegime", "AgeCalendarDays", "Status", "SourceType", "WorkbookValue",
                    "WorkbookSourceURL", "SourceTitle", "SourceFile", "SourceRow", "SourceURL"]
    write_csv(daily_audit_path, daily_audit, audit_fields)
    observation_fields = ["ObservationDate", "AvailableFrom", "BI_Rate", "WorkbookValue", "BI_Instrument",
                          "UnderlyingRegime", "SourceType", "SourceTitle", "WorkbookSeriesNote",
                          "SourceFile", "SourceRow", "WorkbookSourceURL", "SourceURL"]
    write_csv(observation_audit_path, observations, observation_fields)
    raw_workbook_unchanged = sha256(INPUT) == input_hashes_before[str(INPUT)]
    previous_stage_unchanged = sha256(PREVIOUS) == input_hashes_before[str(PREVIOUS)]
    if not raw_workbook_unchanged or not previous_stage_unchanged:
        raise ValueError("Workbook mentah atau kandidat tahap 09 berubah selama proses")

    summary = {
        "status": "historical_BI_rate_filled_candidate_not_model_ready",
        "rows": len(rows),
        "bi_observations_from_workbook": 227,
        "official_transition_corrections": 4,
        "supplemental_precalendar_history": 1,
        "bi_missing_before": sum(not value for value in previous_bi.values()),
        "bi_missing_after": missing_after,
        "historical_rows_filled": filled,
        "rows_legacy_rate": len(legacy_rows),
        "rows_7_day_reverse_repo_regime": len(modern_rows),
        "source_event_coverage": {"first": observations[0]["ObservationDate"], "last": observations[-1]["ObservationDate"]},
        "availability_policy": "decision_date_plus_one_calendar_day_at_00_WIB_due_unknown_intraday_availability",
        "maximum_observation_age_calendar_days": MAX_AGE_DAYS,
        "instrument_rules": {
            "before_2016_08_19": "legacy BI Rate instrument",
            "from_2016_08_19_through_2023_12_20": "BI 7-Day Reverse Repo Rate",
            "from_2023_12_21": "BI-Rate name for same 7-day reverse repo instrument; continuous underlying regime",
            "feature_engineering": "do_not_compute BI rate change across 2016 instrument replacement; 2023 renaming alone does not split the underlying 7-day instrument",
        },
        "modern_values_unchanged_from_stage_09": True,
        "all_non_BI_columns_unchanged": True,
        "raw_workbook_unchanged": raw_workbook_unchanged,
        "previous_stage_unchanged": previous_stage_unchanged,
        "model_ready": False,
        "blockers_inherited": ["historical_volume_incomplete", "remaining_historical_calendar_and_legacy_close_review", "cross_year_volume_scope", "cutoff_and_macro_lag_protocol_not_frozen"],
        "source_sha256": {str(INPUT): sha256(INPUT), str(PREVIOUS): sha256(PREVIOUS), str(metadata["bis_path"]): sha256(metadata["bis_path"]), str(metadata["corrections_path"]): sha256(metadata["corrections_path"])},
        "candidate_sha256": sha256(candidate_path),
        "daily_audit_sha256": sha256(daily_audit_path),
        "observation_audit_sha256": sha256(observation_audit_path),
        "official_sources": {
            "historical_values": BI_PAGE,
            "regime_explanation": BI_HISTORY,
            "2016_instrument_change": POLICY_2016,
            "2023_renaming": POLICY_2023,
        },
    }
    (REPORT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status = f"""# Audit BI Rate — tahap 10

## Hasil

- Kandidat berisi {len(rows):,} tanggal perdagangan IHSG. BI_Rate kosong turun dari {summary['bi_missing_before']:,} menjadi {missing_after}.
- Sebanyak {filled:,} baris historis terisi. Nilai BI modern yang sudah tersedia pada tahap 09 cocok persis dan tidak berubah.
- Workbook mentah berisi 227 keputusan, dari 8 Januari 2008 sampai 22 Juli 2026. Satu nilai awal 6 Desember 2007 sebesar 8% dipertahankan dari seri BIS yang mencatat Bank Indonesia sebagai sumber.
- Kolom selain BI_Rate pada kandidat tahap 09 dipertahankan. File mentah dan hasil tahap 09 tidak ditimpa.

## Pemetaan instrumen

BI mengumumkan BI7DRR berdampingan dengan BI Rate lama sejak April 2016. Workbook hanya memuat BI7DRR untuk rapat 21 April, 19 Mei, 16 Juni, dan 21 Juli 2016, padahal BI Rate lama masih menjadi suku bunga kebijakan. Empat nilai BI Rate lama dipulihkan dari siaran pers BI dan disimpan bersama angka workbook yang asli pada audit. BI7DRR baru menjadi suku bunga kebijakan efektif 19 Agustus 2016. Karena tanggal ketersediaan intrahari historis tidak lengkap, keputusan dipakai mulai hari kalender berikutnya. BI menyatakan perubahan nama pada 21 Desember 2023 tidak mengubah fitur instrumen dan tetap mengacu pada reverse repo tenor 7 hari.

Label historis pada judul kolom workbook (`BI-7Day-RR`) tidak berlaku untuk seluruh rentang. Sebelum April 2016, seri workbook mencatat BI Rate lama. Pada empat tanggal April–Juli 2016, seri tersebut mencatat BI7DRR yang diumumkan bersamaan, bukan BI Rate lama. Mulai 19 Agustus 2016, BI7DRR menjadi suku bunga kebijakan. Sejak 21 Desember 2023 namanya berubah menjadi BI-Rate, dengan fitur dan instrumen reverse repo 7 hari yang sama.

Nilai per hari memakai keputusan terakhir yang sudah tersedia paling lambat pada tanggal tersebut. Batas observasi 62 hari kalender sesuai konfigurasi sumber. Audit mencatat tanggal keputusan, tanggal mulai tersedia, instrumen, umur observasi, baris sumber, dan URL.

## Aturan untuk feature engineering

Jangan menghitung perubahan BI Rate melintasi penggantian instrumen pada 19 Agustus 2016. Perubahan di dalam periode BI Rate lama dan di dalam rezim reverse repo 7 hari dapat dihitung. Perubahan nama pada 21 Desember 2023 tidak dengan sendirinya menjadi batas rezim untuk fitur perubahan.

Nilai BI historis sekarang tersedia di kandidat preprocessing, tetapi fitur belum dihitung ulang dan hasil training lama tidak berubah. Candidate ini tetap belum siap untuk feature engineering/training karena masalah Volume, kalender/Close, cakupan Volume lintas tahun, dan protokol ketersediaan makro.

## Berkas

- Kandidat baru: `../../output/10_bi_rate_history/ihsg_preprocessing_candidate.csv`.
- `bi_rate_daily_audit.csv`: jejak keputusan yang dipakai untuk setiap tanggal IHSG.
- `bi_rate_observation_audit.csv`: seluruh observasi sumber beserta klasifikasi instrumen.
- `summary.json`: checksum, cakupan, rekonsiliasi, dan status gate.

## Sumber resmi

- [Indikator BI-Rate dan data historis]({BI_PAGE})
- [Keterangan BI tentang BI7DRR dan perubahan nama 2023]({BI_HISTORY})
- [Keputusan BI 18–19 Agustus 2016]({POLICY_2016})
- [PBI Nomor 15 Tahun 2023]({POLICY_2023})
- [Siaran pers BI 21 April 2016](https://www.bi.go.id/id/publikasi/ruang-media/news-release/Pages/sp_183116.aspx)
- [Siaran pers BI 19 Mei 2016](https://www.bi.go.id/id/publikasi/ruang-media/news-release/Pages/SP_183816.aspx)
- [Siaran pers BI 16 Juni 2016](https://www.bi.go.id/id/publikasi/ruang-media/news-release/Pages/SP_185016.aspx)
- [Siaran pers BI 21 Juli 2016](https://www.bi.go.id/id/publikasi/ruang-media/news-release/Pages/SP_185616.aspx)
"""
    (REPORT_DIR / "STATUS_BI_RATE.md").write_text(status, encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"source_sha256", "official_sources"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
