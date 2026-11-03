"""Bentuk target, threshold training, split waktu, dan lima fold walk-forward.

Jalankan: python build_targets.py
Hasil tetap eksperimen awal mengikuti keterbatasan sumber feature engineering.
"""
from __future__ import annotations

# 1. Seluruh operasi memakai pustaka standar; sumber CSV hanya dibaca.
import argparse
import csv
import hashlib
import json
import math
import platform
import shutil
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from feature_engineering import CORE, HERE

LABELS = {0: "Bearish", 1: "Sideways", 2: "Bullish"}
EXTRA_COLUMNS = [
    "calendar_index", "label_end_date", "future_return_5d", "target_status",
    "core_features_complete", "eligible_for_split", "eligibility_reason",
    "current_regime", "current_regime_code", "future_regime", "y_t",
    "base_split", "initial_split_status", "purged_before_final_test",
]


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quantile_linear(values, probability):
    """Interpolasi linear pada posisi (n−1)q, sesuai kuantil PRD."""
    if not values or not 0 <= probability <= 1:
        raise ValueError("Sampel kuantil kosong atau probabilitas tidak valid")
    values = sorted(values)
    position = (len(values) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def regime(value, lower, upper):
    """Kedua batas termasuk Sideways; missing tetap missing."""
    if value is None:
        return None
    return 0 if value < lower else 2 if value > upper else 1


def form_targets(rows, horizon=5):
    """Tentukan t+5 sebelum menyaring fitur atau harga kosong."""
    dates = [r["Date"] for r in rows]
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        raise ValueError("Kalender harus terurut dan tanpa tanggal duplikat")
    if horizon != 5:
        raise ValueError("PRD dan nama kolom menetapkan horizon lima hari perdagangan")
    output = []
    for i, original in enumerate(rows):
        current = original["Close"]
        end = rows[i + horizon] if i + horizon < len(rows) else None
        value = None
        if end is None:
            status = "horizon_not_yet_available"
        elif current is None:
            status = "current_close_missing"
        elif current <= 0:
            status = "current_close_nonpositive"
        elif end["Close"] is None:
            status = "future_close_missing"
        elif end["Close"] <= 0:
            status = "future_close_nonpositive"
        else:
            value = end["Close"] / current - 1
            status = "available"
        complete = all(original[c] is not None for c in CORE)
        reasons = ([] if complete else ["missing_core_features"])
        if value is None:
            reasons.append(status)
        output.append({**original, "calendar_index": i,
                       "label_end_date": end["Date"] if end else None,
                       "future_return_5d": value, "target_status": status,
                       "core_features_complete": complete,
                       "eligible_for_split": not reasons,
                       "eligibility_reason": "|".join(reasons)})
    return output


def purge_before(pool, evaluation_start, calendar, horizon=5):
    """Gap dihitung pada kalender lengkap, bukan lima sampel tersisa."""
    start_index = next(r["calendar_index"] for r in calendar
                       if r["Date"] == evaluation_start)
    gap_start = max(0, start_index - horizon)
    gap_dates = [r["Date"] for r in calendar[gap_start:start_index]]
    kept, removed = [], []
    for r in pool:
        if r["Date"] >= evaluation_start:
            raise ValueError("Pool training melewati awal evaluasi")
        in_gap = r["calendar_index"] >= gap_start
        crosses = r["label_end_date"] is None or r["label_end_date"] >= evaluation_start
        if in_gap or crosses:
            removed.append(r)
        else:
            kept.append(r)
    if any(r["label_end_date"] >= evaluation_start for r in kept):
        raise AssertionError("Horizon label training memasuki evaluasi")
    return kept, removed, gap_dates


def describe(rows):
    return {"rows": len(rows), "start_date": rows[0]["Date"] if rows else None,
            "end_date": rows[-1]["Date"] if rows else None,
            "class_counts": {name: sum(r["y_t"] == code for r in rows)
                             for code, name in LABELS.items()}}


def prepare(rows):
    """Hitung batas split tanpa kelas; kalibrasi hanya initial training setelah purge."""
    calendar = form_targets(rows)
    eligible = [r for r in calendar if r["eligible_for_split"]]
    count = len(eligible)
    train_count, val_count = count * 3 // 5, count // 5
    if train_count < 10 or val_count < 5 or count - train_count - val_count < 1:
        raise ValueError("Sampel tidak cukup untuk split dan lima fold validation")
    initial = eligible[:train_count]
    validation_base = eligible[train_count:train_count + val_count]
    test = eligible[train_count + val_count:]
    train, train_purged, initial_gap = purge_before(initial, validation_base[0]["Date"], calendar)
    development = eligible[:train_count + val_count]
    dev_train, dev_purged, dev_gap = purge_before(development, test[0]["Date"], calendar)
    # Label validation juga tidak boleh memakai harga dari sisi final test.
    # Baris purge batas test dikeluarkan sebelum pembentukan lima blok tuning.
    kept_development_dates = {r["Date"] for r in dev_train}
    validation = [r for r in validation_base if r["Date"] in kept_development_dates]
    if len(validation) < 5:
        raise ValueError("Validation tidak cukup untuk lima fold setelah purge batas test")
    if not train:
        raise ValueError("Training kosong setelah purge")

    # 2. Threshold tidak di-fit pada validation, test, atau fold berikutnya.
    values = [r["future_return_5d"] for r in train]
    lower, upper = quantile_linear(values, .33), quantile_linear(values, .67)
    if lower >= upper:
        raise ValueError("Kalibrasi gagal: threshold sama atau terbalik")
    for r in calendar:
        r["y_t"] = regime(r["future_return_5d"], lower, upper)
        r["future_regime"] = LABELS.get(r["y_t"])
        r["current_regime_code"] = regime(r["ihsg_return_5d"], lower, upper)
        r["current_regime"] = LABELS.get(r["current_regime_code"])
    if {r["y_t"] for r in train} != {0, 1, 2}:
        raise ValueError("Kalibrasi training tidak menghasilkan tiga kelas")

    # 3. Status awal dan development dibedakan agar purge final tidak menghapus validation.
    for r in calendar:
        r.update(base_split=None, initial_split_status="excluded_incomplete",
                 purged_before_final_test=False)
    for name, block in [("train", initial), ("validation", validation_base), ("test", test)]:
        for r in block:
            r.update(base_split=name, initial_split_status=name)
    for r in train_purged:
        r["initial_split_status"] = "purged_initial_train"
    for r in dev_purged:
        r["purged_before_final_test"] = True
        r["initial_split_status"] = "purged_development_test"
    audits = []
    def add_audit(context, removed, start):
        audits.extend({"Context": context, "Date": r["Date"],
                       "label_end_date": r["label_end_date"], "EvaluationStart": start,
                       "Reason": "five_calendar_positions_or_label_horizon_overlaps"}
                      for r in removed)
    add_audit("initial_train_validation", train_purged, validation[0]["Date"])
    add_audit("development_test", dev_purged, test[0]["Date"])

    # 4. Lima blok validation berurutan; pool training bertambah pada tiap fold.
    folds, offset = [], 0
    size, remainder = divmod(len(validation), 5)
    for index in range(5):
        block = validation[offset:offset + size + (index < remainder)]
        pool = [*initial, *validation[:offset]]
        fold_train, removed, gap = purge_before(pool, block[0]["Date"], calendar)
        folds.append({"fold": index + 1, "train": fold_train, "validation": block,
                      "purged": removed, "gap_dates": gap})
        add_audit(f"fold_{index + 1}", removed, block[0]["Date"])
        offset += len(block)
    excluded = [r for r in calendar if not r["eligible_for_split"]]
    calibration = {"T_B": lower, "T_U": upper, "unit": "decimal_return",
                   "quantiles": [.33, .67], "interpolation": "linear",
                   "sample_count": len(train), "start_date": train[0]["Date"],
                   "end_date": train[-1]["Date"],
                   "max_label_end_date": max(r["label_end_date"] for r in train),
                   "validation_start_date": validation[0]["Date"],
                   "thresholds_bracket_zero": lower < 0 < upper,
                   "status": "valid" if lower < 0 < upper else "review_required_relative_quantile_labels",
                   "class_counts": describe(train)["class_counts"],
                   "sample_dates_sha256": hashlib.sha256(
                       "\n".join(r["Date"] for r in train).encode()).hexdigest(),
                   "frozen_for_all_validation_folds_and_final_test": True}
    return {"calendar": calendar, "eligible": eligible, "train": train,
            "validation": validation, "test": test, "development_train": dev_train,
            "excluded": excluded, "purge_audit": audits, "folds": folds,
            "calibration": calibration, "split_counts_before_purge": {
                "train": len(initial), "validation": len(validation_base), "test": len(test)},
            "gap_dates": {"initial_train_validation": initial_gap, "development_test": dev_gap},
            "purged_counts": {"initial_train_validation": len(train_purged),
                              "development_test": len(dev_purged)}}


def load_input(path):
    """Hentikan proses jika tanggal, header, atau angka masukan tidak valid."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        if not fields or len(set(fields)) != len(fields):
            raise ValueError("Header tidak ada atau duplikat")
        if not {"Date", "Close", *CORE, "bi_rate_change", "inflation_yoy"} <= set(fields):
            raise ValueError("Masukan harus berupa gabungan preprocessing dan fitur lengkap")
        if set(fields) & set(EXTRA_COLUMNS):
            raise ValueError("Masukan sudah memiliki kolom target; gunakan hasil feature engineering")
        rows = []
        for raw in reader:
            if None in raw or any(v is None for v in raw.values()):
                raise ValueError("Jumlah kolom CSV tidak konsisten")
            date.fromisoformat(raw["Date"])
            row = {"Date": raw["Date"]}
            for key in fields:
                if key == "Date":
                    continue
                value = None if raw[key] == "" else float(raw[key])
                if value is not None and not math.isfinite(value):
                    raise ValueError(f"Angka tidak finite pada {raw['Date']} / {key}")
                row[key] = value
            rows.append(row)
    if not rows:
        raise ValueError("Masukan kosong")
    return rows, fields


def main(input_path=None, output_dir=None):
    source = Path(input_path or HERE / "output/ihsg_preprocessing_features_all.csv").resolve()
    out = Path(output_dir or HERE / "output/targets").resolve()
    before_hash = fingerprint(source)
    if source.is_relative_to(out):
        raise ValueError("Folder output target tidak boleh mencakup berkas fitur sumber.")
    report_path = source.parent / "feature_report.json"
    report_hash = fingerprint(report_path) if report_path.exists() else None
    upstream = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    expected = upstream.get("outputs", {}).get(source.name)
    if expected and expected != before_hash:
        raise ValueError("Masukan berbeda dari checksum laporan; jalankan ulang feature_engineering.py")
    rows, fields = load_input(source)
    result = prepare(rows)
    # Simpan bundle sebelumnya agar run model lama tetap dapat ditelusuri.
    archive = None
    previous_metadata = out / "split_metadata.json"
    if previous_metadata.exists():
        previous = json.loads(previous_metadata.read_text(encoding="utf-8"))
        if previous.get("input_sha256") != before_hash:
            archive = source.parent / "archive" / datetime.now(timezone.utc).strftime("targets_before_rebuild_%Y%m%dT%H%M%S_%fZ")
            shutil.copytree(out, archive)
    out.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    def save(name, records, columns=None):
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        columns = columns or [*fields, *EXTRA_COLUMNS]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows({c: r.get(c) for c in columns} for r in records)
        artifacts[name] = {"rows": len(records), "sha256": fingerprint(path)}

    # 5. Simpan data lengkap, subset, jejak pengecualian, dan fold yang dapat diulang.
    save("ihsg_features_targets_all.csv", result["calendar"])
    save("eligible_labeled.csv", result["eligible"])
    for name in ["train", "validation", "test", "development_train"]:
        save(f"splits/{name}.csv", result[name])
    save("excluded_rows.csv", result["excluded"],
         ["Date", "label_end_date", "core_features_complete", "target_status", "eligibility_reason"])
    save("purge_audit.csv", result["purge_audit"],
         ["Context", "Date", "label_end_date", "EvaluationStart", "Reason"])
    fold_metadata = []
    for fold in result["folds"]:
        number = fold["fold"]
        train_path, val_path = f"folds/fold_{number}_train.csv", f"folds/fold_{number}_validation.csv"
        save(train_path, fold["train"])
        save(val_path, fold["validation"])
        fold_metadata.append({"fold": number, "train": describe(fold["train"]),
                              "validation": describe(fold["validation"]),
                              "purged_training_rows": len(fold["purged"]),
                              "purge_calendar_dates": fold["gap_dates"],
                              "train_file": train_path, "validation_file": val_path})

    # X hanya nama fitur yang disetujui; return masa depan/label/status bukan X.
    contract = {"class_order": [0, 1, 2], "class_names": LABELS,
                "target_column": "y_t", "horizon_trading_days": 5,
                "feature_sets": {"core": CORE,
                                 "core_plus_bi": [*CORE, "bi_rate_change"],
                                 "core_plus_inflation": [*CORE, "inflation_yoy"],
                                 "core_plus_both": [*CORE, "bi_rate_change", "inflation_yoy"]},
                "candidate_comparison": "Use identical dates and folds on common candidate availability; never fill candidate gaps from future observations.",
                "forbidden_input_columns": [c for c in [*fields, *EXTRA_COLUMNS]
                                            if c not in [*CORE, "bi_rate_change", "inflation_yoy"]],
                "model_ready": False}
    metadata = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                "status": "exploratory_target_and_split_complete_not_training_approved",
                "input_file": str(source), "input_sha256": before_hash,
                "feature_report_sha256": fingerprint(report_path) if report_path.exists() else None,
                "preprocessing_file": upstream.get("input_file"),
                "preprocessing_sha256": upstream.get("raw_sha256"),
                "preprocessing_approved_for_feature_engineering": upstream.get("preprocessing_approved_for_feature_engineering", False),
                "previous_target_archive": str(archive) if archive else None,
                "script_sha256": fingerprint(__file__), "python_version": platform.python_version(),
                "calendar_rows": len(rows), "calendar_status": "inherited_provisional_calendar_no_new_verification",
                "eligible_rows": len(result["eligible"]), "excluded_rows": len(result["excluded"]),
                "target_status_counts": dict(Counter(r["target_status"] for r in result["calendar"])),
                "latest_unlabeled_dates": [r["Date"] for r in result["calendar"]
                                           if r["target_status"] == "horizon_not_yet_available"],
                "split_ratios": [0.6, 0.2, 0.2],
                "rounding": "floor(3N/5) train, floor(N/5) validation, remainder test; before purge",
                "split_counts_before_purge": result["split_counts_before_purge"],
                "splits_after_purge": {n: describe(result[n]) for n in
                                       ["train", "validation", "test", "development_train"]},
                "purge_horizon_trading_days": 5, "purge_calendar_dates": result["gap_dates"],
                "purged_counts": result["purged_counts"], "validation_folds": fold_metadata,
                "calibration": result["calibration"], "model_ready": False,
                "models_trained": False, "limitations": upstream.get("limitations", [])[:3],
                "artifacts": artifacts}
    for name, data in [("thresholds.json", result["calibration"]),
                       ("model_contract.json", contract), ("split_metadata.json", metadata)]:
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if fingerprint(source) != before_hash:
        raise RuntimeError("Masukan berubah selama proses")
    # Sinkronkan penanda versi target pada laporan fitur tanpa mengubah CSV fitur.
    if report_path.exists():
        if fingerprint(report_path) != report_hash:
            raise RuntimeError("Laporan fitur berubah selama pembentukan target")
        upstream["targets_and_splits"] = {
            "status": "current",
            "action": "Target, threshold, split, dan fold sudah dibangun dari versi fitur ini.",
            "current_feature_sha256": before_hash,
            "target_metadata_file": str(out / "split_metadata.json"),
            "updated_at_utc": metadata["created_at_utc"],
        }
        report_path.write_text(json.dumps(upstream, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        metadata["feature_report_sha256"] = fingerprint(report_path)
        (out / "split_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 6. Laporan singkat membedakan baris berlabel dan yang menunggu horizon.
    summary = result["calibration"]
    split_table = "\n".join(
        f"| {name} | {value['rows']} | {value['start_date']} | {value['end_date']} |"
        for name, value in metadata["splits_after_purge"].items())
    (out / "TARGET_DAN_SPLIT.md").write_text(f"""# Target dan pembagian data

Status: eksperimen awal; model belum dilatih. Keterbatasan kalender, Volume,
dan waktu tersedia makro yang tercatat pada laporan fitur tetap berlaku.

## Hasil

- Kalender lengkap: {len(rows)} tanggal; tidak dipadatkan sebelum menghitung t+5.
- Layak berdasarkan 13 fitur inti dan future return: {len(result['eligible'])} baris.
- Dikecualikan dari split: {len(result['excluded'])} baris; alasan pada `excluded_rows.csv`.
- Lima tanggal terbaru belum punya harga t+5; `label_end_date` dan target tetap kosong.
- Target memakai kedua endpoint Close, tanpa menebak Close yang kosong di endpoint.
- Pembagian 60:20:20 menggunakan jumlah observasi layak sebelum purge.
- Purge dihitung pada lima posisi kalender lengkap; setiap label training harus
  berakhir sebelum awal evaluasi. Detail setiap batas ada pada `purge_audit.csv`.
- Label validation yang menyentuh sisi final test juga dikeluarkan sebelum
  lima fold dibentuk; pemilihan model tidak memakai harga dari sisi final test.

| Subset | Baris | Awal | Akhir |
|---|---:|---|---|
{split_table}

## Label dan ambang

Kuantil training setelah purge: T_B={summary['T_B']:.12g} dan T_U={summary['T_U']:.12g}
dalam rasio desimal. Interpolasi linear, sampel {summary['sample_count']} baris.
Status kalibrasi: {summary['status']}. Ambang dibekukan untuk seluruh fold dan test.
Return di bawah T_B adalah Bearish (0), kedua batas termasuk Sideways (1), dan
return di atas T_U adalah Bullish (2). Current regime memakai return historis 5D
dengan ambang yang sama untuk tampilan; tidak menjadi fitur model.

## Berkas

`ihsg_features_targets_all.csv` memuat data asal, fitur, target, tanggal akhir
label, dan status split dalam satu tabel. `splits/` memuat train, validation,
test, serta development training setelah purge. `folds/` memuat lima pasangan
training/validation dengan jendela training yang bertambah. `thresholds.json`
menyimpan kalibrasi, `split_metadata.json` menyimpan tanggal batas dan checksum.

Saat melatih model, gunakan hanya daftar fitur dalam `model_contract.json`.
Jangan memakai seluruh kolom numerik sebagai X. Label/return masa depan dan
tanggal/status bukan masukan model. Kandidat domestik dibandingkan pada
tanggal bersama yang lengkap; nilai kandidat kosong tidak diisi dari masa depan.
Final test belum dievaluasi dan tidak digunakan untuk pemilihan fitur/ambang.
""", encoding="utf-8")
    # Penanda dari perhitungan fitur tidak boleh tetap menyebut split ini usang
    # setelah target berhasil dibangun dari checksum fitur terbaru.
    (out / "STATUS_FEATURE_INPUT.md").write_text(
        "# Target dan split sesuai versi fitur ini\n\n"
        f"Dibangun dari `{source}` dengan SHA-256 `{before_hash}`. "
        "Status tetap eksplorasi mengikuti kualitas sumber pada laporan fitur.\n",
        encoding="utf-8",
    )
    print(json.dumps({"calendar_rows": len(rows), "eligible_rows": len(result["eligible"]),
                      "excluded_rows": len(result["excluded"]),
                      "splits_after_purge": metadata["splits_after_purge"],
                      "T_B": summary["T_B"], "T_U": summary["T_U"],
                      "calibration_status": summary["status"], "model_ready": False}, indent=2))
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    main(args.input, args.output_dir)
