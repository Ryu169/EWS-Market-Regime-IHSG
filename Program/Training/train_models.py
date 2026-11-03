"""Latih baseline CPU dengan lima fold tersimpan; final test tidak dibaca.

Contoh: python train_models.py --check-data
        python train_models.py --smoke
        python train_models.py
"""
from __future__ import annotations

# 1. Validasi data dan --check-data hanya memerlukan pustaka standar Python.
import argparse
import csv
import hashlib
import importlib
import importlib.metadata
import json
import math
import platform
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

# Modul baseline 13 fitur ini juga menyediakan pembaca data/metrik untuk
# train_inflation_change.py (alur terbaru 15 fitur). Gunakan skrip terbaru
# tersebut bila ingin melatih BI-Rate Change dan Inflation Change sekaligus.
HERE = Path(__file__).resolve().parent
CLASSES = [0, 1, 2]
NAMES = ["Bearish", "Sideways", "Bullish"]
CORE = ["ihsg_return_1d", "ihsg_return_5d", "ma_5", "ma_20", "ma_ratio",
        "volatility_5d", "volatility_20d", "rsi_14", "volume_change",
        "foreign_net_5d", "usdidr_return", "brent_return", "us10y_change"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, content):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(content, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, rows, fields):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def validate_features(contract):
    """Whitelist eksplisit mencegah label/return masa depan masuk ke X."""
    features = contract["feature_sets"]["core"]
    if features != CORE or len(set(features)) != 13:
        raise ValueError("Daftar/urutan 13 fitur inti berbeda dari baseline PRD")
    if set(features) & set(contract["forbidden_input_columns"]):
        raise ValueError("Kontrak fitur memasukkan kolom yang dilarang")
    if contract["class_order"] != CLASSES or contract["target_column"] != "y_t":
        raise ValueError("Urutan kelas atau kolom target tidak sesuai kontrak")
    return features


def load_table(root, name, artifacts, features, thresholds):
    """Baca hanya file development/fold yang diizinkan, dengan checksum."""
    allowed = {f"folds/fold_{i}_{part}.csv" for i in range(1, 6)
               for part in ["train", "validation"]} | {"splits/development_train.csv"}
    if name not in allowed:
        raise ValueError(f"File tidak diizinkan untuk training baseline: {name}")
    path = root / name
    expected = artifacts[name]
    if sha256(path) != expected["sha256"]:
        raise ValueError(f"Checksum berubah: {name}; jalankan ulang build_targets.py")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"Header duplikat atau kosong: {name}")
        required = {"Date", "label_end_date", "calendar_index", "y_t",
                    "future_return_5d", *features}
        if not required <= set(reader.fieldnames):
            raise ValueError(f"Kolom wajib tidak lengkap: {name}")
        rows = list(reader)
    if not rows or len(rows) != expected["rows"]:
        raise ValueError(f"Jumlah baris berubah atau kosong: {name}")
    for row in rows:
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"Struktur CSV rusak: {name}")
        for key in ["Date", "label_end_date"]:
            if date.fromisoformat(row[key]).isoformat() != row[key]:
                raise ValueError(f"Format tanggal tidak ISO: {name}")
        if row["label_end_date"] <= row["Date"]:
            raise ValueError(f"Tanggal akhir label tidak di masa depan: {name}")
        for column in features:
            if row[column] == "" or not math.isfinite(float(row[column])):
                raise ValueError(f"Fitur kosong/nonfinite: {name} {row['Date']} {column}")
        target = float(row["y_t"])
        if not target.is_integer() or int(target) not in CLASSES:
            raise ValueError(f"Target tidak valid: {name}")
        row["y_t"] = int(target)
        row["calendar_index"] = int(row["calendar_index"])
        value = float(row["future_return_5d"])
        if not math.isfinite(value):
            raise ValueError(f"Future return tidak finite: {name}")
        expected_class = 0 if value < thresholds["T_B"] else 2 if value > thresholds["T_U"] else 1
        if row["y_t"] != expected_class:
            raise ValueError(f"Target berbeda dari threshold beku: {name}")
    dates = [r["Date"] for r in rows]
    indices = [r["calendar_index"] for r in rows]
    if dates != sorted(set(dates)) or indices != sorted(set(indices)):
        raise ValueError(f"Tanggal/indeks tidak terurut unik: {name}")
    return rows


def validate_boundary(training, validation, test_start):
    """Label training dan validation tidak boleh melewati batas evaluasi."""
    start = validation[0]["Date"]
    if training[-1]["Date"] >= start:
        raise ValueError("Tanggal training memasuki validation")
    if max(r["label_end_date"] for r in training) >= start:
        raise ValueError("Horizon training menyentuh validation")
    if training[-1]["calendar_index"] >= validation[0]["calendar_index"] - 5:
        raise ValueError("Purge lima posisi kalender belum diterapkan")
    if max(r["label_end_date"] for r in validation) >= test_start:
        raise ValueError("Horizon validation menyentuh final test")


def load_bundle(config, config_dir):
    """Muat lima fold tersimpan; tidak membuka CSV final test maupun tabel all."""
    # data_dir di konfigurasi menunjuk folder hasil feature engineering/targets.
    # CSV fold sudah memiliki fitur X, label y_t, dan metadata tanggal.
    # Pembagian waktu tidak diacak ulang di sini.
    root = (config_dir / config["data_dir"]).resolve()
    meta = read_json(root / "split_metadata.json")
    contract = read_json(root / "model_contract.json")
    thresholds = read_json(root / "thresholds.json")
    features = validate_features(contract)
    if config["feature_set"] != "core":
        raise ValueError("Skrip ini khusus baseline 13 fitur inti")
    if not (math.isfinite(thresholds["T_B"]) and math.isfinite(thresholds["T_U"])
            and thresholds["T_B"] < 0 < thresholds["T_U"]):
        raise ValueError("Threshold harus valid dan mengapit nol sebelum baseline ini dilatih")
    if thresholds != meta["calibration"] or not thresholds["frozen_for_all_validation_folds_and_final_test"]:
        raise ValueError("Threshold berbeda dari metadata atau tidak dibekukan")
    if meta["purge_horizon_trading_days"] != 5 or len(meta["validation_folds"]) != 5:
        raise ValueError("Diperlukan horizon lima hari dan lima fold")
    test_start = meta["splits_after_purge"]["test"]["start_date"]
    folds, seen_validation, previous_train = [], [], set()
    for expected_id, spec in enumerate(meta["validation_folds"], 1):
        if spec["fold"] != expected_id:
            raise ValueError("Urutan fold berubah")
        tr = load_table(root, spec["train_file"], meta["artifacts"], features, thresholds)
        va = load_table(root, spec["validation_file"], meta["artifacts"], features, thresholds)
        validate_boundary(tr, va, test_start)
        for rows, stats in [(tr, spec["train"]), (va, spec["validation"])]:
            if (len(rows), rows[0]["Date"], rows[-1]["Date"]) != (
                stats["rows"], stats["start_date"], stats["end_date"]):
                raise ValueError("Tanggal/jumlah fold berbeda dari metadata")
        train_dates = {r["Date"] for r in tr}
        if not previous_train <= train_dates or {r["y_t"] for r in tr} != set(CLASSES):
            raise ValueError("Training tidak bertambah atau tidak memiliki tiga kelas")
        previous_train = train_dates
        seen_validation.extend(r["Date"] for r in va)
        folds.append({"fold": expected_id, "train": tr, "validation": va})
    validation_stats = meta["splits_after_purge"]["validation"]
    if seen_validation != sorted(set(seen_validation)) or len(seen_validation) != validation_stats["rows"]:
        raise ValueError("Fold tidak menutupi validation satu kali secara berurutan")
    if (seen_validation[0], seen_validation[-1]) != (validation_stats["start_date"], validation_stats["end_date"]):
        raise ValueError("Rentang validation berbeda")
    development = load_table(root, "splits/development_train.csv", meta["artifacts"], features, thresholds)
    if max(r["label_end_date"] for r in development) >= test_start:
        raise ValueError("Horizon development training menyentuh test")
    if len(development) != meta["splits_after_purge"]["development_train"]["rows"]:
        raise ValueError("Jumlah development training berubah")
    input_names = ["split_metadata.json", "model_contract.json", "thresholds.json",
                   "splits/development_train.csv"]
    input_names += [spec[key] for spec in meta["validation_folds"]
                    for key in ["train_file", "validation_file"]]
    return {"features": features, "folds": folds, "development": development,
            "thresholds": thresholds, "metadata": meta, "root": root,
            "input_hashes": {name: sha256(root/name) for name in input_names},
            "model_ready": False}


# 2. Metrik disimpan dengan denominator nol sebagai null, disertai alasan.
def divide(numerator, denominator):
    return numerator / denominator if denominator else None


def metrics(actual, predicted):
    if not actual or len(actual) != len(predicted):
        raise ValueError("Label dan prediksi kosong atau berbeda panjang")
    cm = [[0] * 3 for _ in CLASSES]
    for a, p in zip(actual, predicted):
        if a not in CLASSES or p not in CLASSES:
            raise ValueError("Kelas di luar urutan 0,1,2")
        cm[a][p] += 1
    per_class, undefined = {}, {}
    for code, name in enumerate(NAMES):
        tp = cm[code][code]
        fn = sum(cm[code]) - tp
        fp = sum(row[code] for row in cm) - tp
        values = {"precision": divide(tp, tp + fp), "recall": divide(tp, tp + fn),
                  "f1": divide(2*tp, 2*tp + fp + fn), "support": tp + fn}
        per_class[name] = values
        for key in ["precision", "recall", "f1"]:
            if values[key] is None:
                undefined[f"{name}.{key}"] = "zero_denominator"
    macro = {}
    for key in ["precision", "recall", "f1"]:
        values = [per_class[name][key] for name in NAMES]
        macro[f"macro_{key}"] = statistics.mean(values) if None not in values else None
        if None in values:
            undefined[f"macro_{key}"] = "at_least_one_class_metric_undefined"
    tp, fn = cm[0][0], sum(cm[0][1:])
    fp = cm[1][0] + cm[2][0]
    tn = len(actual) - tp - fn - fp
    warning = {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
               "actual_bearish": tp + fn, "actual_non_bearish": fp + tn,
               "precision_warning": divide(tp, tp+fp),
               "recall_warning": divide(tp, tp+fn),
               "false_alarm_rate": divide(fp, fp+tn), "miss_rate": divide(fn, tp+fn)}
    for key, value in warning.items():
        if value is None:
            undefined[f"warning.{key}"] = "zero_denominator"
    return {"rows": len(actual), "accuracy": sum(cm[i][i] for i in CLASSES)/len(actual),
            **macro, "recall_bearish": per_class["Bearish"]["recall"],
            "per_class": per_class, "confusion_matrix": cm,
            "matrix_order": NAMES, "warning": warning, "undefined_reasons": undefined}


def summarize(fold_results):
    result = {}
    for metric in ["accuracy", "macro_precision", "macro_recall", "macro_f1", "recall_bearish"]:
        values = [r[metric] for r in fold_results if r[metric] is not None]
        all_defined = len(values) == len(fold_results)
        result[metric] = {"mean": statistics.mean(values) if all_defined else None,
                          "std": statistics.stdev(values) if all_defined and len(values)>1 else None,
                          "defined_folds": len(values), "total_folds": len(fold_results),
                          "std_ddof": 1}
    return result


def select_baseline(summaries, tolerance):
    """Aturan seri diputuskan dalam konfigurasi sebelum skor dilihat."""
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Toleransi seleksi harus finite dan tidak negatif")
    if any(s["macro_f1"]["mean"] is None or s["macro_f1"]["std"] is None
           for s in summaries.values()):
        raise ValueError("Pemilihan baseline tidak dapat memakai Macro F1 yang tidak terdefinisi")
    best = max(s["macro_f1"]["mean"] for s in summaries.values())
    close = [name for name, s in summaries.items()
             if best - s["macro_f1"]["mean"] <= tolerance]
    return min(close, key=lambda name: (summaries[name]["macro_f1"]["std"],
                                       -summaries[name]["accuracy"]["mean"], name))


# 3. Dependency ML baru diimpor untuk training, bukan untuk pemeriksaan data.
def dependencies(names):
    try:
        modules = {"numpy": importlib.import_module("numpy"),
                   "joblib": importlib.import_module("joblib")}
        modules.update({name: importlib.import_module(name) for name in names})
        return modules
    except (ImportError, OSError) as exc:
        raise RuntimeError("Dependency training belum siap. Aktifkan .venv dan jalankan "
                           "python -m pip install -r requirements.txt. Jika libomp.dylib "
                           "tidak ditemukan di Mac, jalankan brew install libomp. "
                           f"Detail: {exc}") from exc


def make_model(name, config, modules):
    params = {**config[name], "n_estimators": config["trees"],
              "n_jobs": config["jobs"], "random_state": config["seed"]}
    classifier = modules[name].XGBClassifier if name == "xgboost" else modules[name].LGBMClassifier
    return classifier(**params), params


def matrix(rows, features, np):
    # Hanya kolom whitelist `features` yang masuk X. Baris CSV lain seperti
    # Date, Close, future_return_5d, dan y_t tidak ikut sebagai fitur.
    return np.asarray([[float(r[c]) for c in features] for r in rows], dtype=np.float64)


def probabilities(model, values, np):
    """Petakan probabilitas memakai classes_, jangan mengasumsikan urutan kolom."""
    classes = [int(c) for c in model.classes_]
    if sorted(classes) != CLASSES:
        raise ValueError("Model tidak mempunyai tepat tiga kelas")
    raw = np.asarray(model.predict_proba(values), dtype=float)
    if raw.shape != (len(values), 3) or not np.isfinite(raw).all() or (raw < 0).any():
        raise ValueError("Probabilitas model tidak valid")
    ordered = raw[:, [classes.index(c) for c in CLASSES]]
    if not np.allclose(ordered.sum(axis=1), 1, atol=1e-5):
        raise ValueError("Probabilitas tidak berjumlah satu")
    return ordered, ordered.argmax(axis=1).tolist()


def run_training(config, bundle, out, smoke):
    modules = dependencies(config["models"])
    np, joblib = modules["numpy"], modules["joblib"]
    versions = {n: importlib.metadata.version(n) for n in
                ["numpy", "scipy", "scikit-learn", "joblib", *config["models"]]}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/"run_status.json", {"status": "running", "mode": "smoke" if smoke else "baseline"})
    write_json(out/"experiment_config.json", config)
    results, summaries = {}, {}
    start_run = time.perf_counter()
    try:
        for name in config["models"]:
            fold_results, prediction_rows = [], []
            for fold in bundle["folds"]:
                number = fold["fold"]
                print(f"[{name}] fold {number}/5: train={len(fold['train'])}, validation={len(fold['validation'])}", flush=True)
                model, params = make_model(name, config, modules)
                x_train = matrix(fold["train"], bundle["features"], np)
                x_val = matrix(fold["validation"], bundle["features"], np)
                # y_train adalah kelas masa depan (0/1/2), diberikan terpisah
                # dari X. Label validation tidak diberikan ke model.fit.
                y_train = np.asarray([r["y_t"] for r in fold["train"]], dtype=int)
                started = time.perf_counter()
                # Validation tidak masuk fit/early stopping pada baseline tetap ini.
                model.fit(x_train, y_train)
                fit_seconds = time.perf_counter() - started
                proba, predicted = probabilities(model, x_val, np)
                score = metrics([r["y_t"] for r in fold["validation"]], predicted)
                fold_results.append(score)
                path = out/name/f"fold_{number}"
                write_json(path/"metrics.json", {**score, "fit_seconds": fit_seconds, "parameters": params})
                write_csv(path/"confusion_matrix.csv",
                          [{"Actual": label, **dict(zip(NAMES, score["confusion_matrix"][i]))}
                           for i, label in enumerate(NAMES)], ["Actual", *NAMES])
                joblib.dump(model, path/"model.joblib")
                for row, probs, pred in zip(fold["validation"], proba, predicted):
                    prediction_rows.append({"Fold": number, "Date": row["Date"],
                                            "label_end_date": row["label_end_date"],
                                            "y_true": row["y_t"], "y_pred": pred,
                                            "ActualRegime": NAMES[row["y_t"]], "PredictedRegime": NAMES[pred],
                                            **{f"p_{label.lower()}": float(probs[i]) for i, label in enumerate(NAMES)}})
                f1_text = 'n/a' if score['macro_f1'] is None else f"{score['macro_f1']:.4f}"
                recall_text = 'n/a' if score['recall_bearish'] is None else f"{score['recall_bearish']:.4f}"
                print(f"  Accuracy={score['accuracy']:.4f}, Macro F1={f1_text}, Recall Bearish={recall_text}, {fit_seconds:.2f}s", flush=True)
            summaries[name] = summarize(fold_results)
            results[name] = {"fold_metrics": fold_results, "summary": summaries[name],
                             "pooled_validation": metrics([r["y_true"] for r in prediction_rows],
                                                          [r["y_pred"] for r in prediction_rows])}
            write_csv(out/name/"validation_predictions.csv", prediction_rows, list(prediction_rows[0]))
            # Simpan model development untuk eksplorasi, tanpa membuka final test.
            if config["refit_development"]:
                model, params = make_model(name, config, modules)
                development = bundle["development"]
                x = matrix(development, bundle["features"], np)
                y = np.asarray([r["y_t"] for r in development], dtype=int)
                started = time.perf_counter()
                model.fit(x, y)
                refit_seconds = time.perf_counter()-started
                path = out/name/"development_model"
                path.mkdir(parents=True, exist_ok=True)
                joblib.dump(model, path/"model.joblib")
                # Uji bahwa artefak yang disimpan bisa dibaca dan memprediksi ulang.
                loaded = joblib.load(path/"model.joblib")
                expected, _ = probabilities(model, x[:5], np)
                restored, _ = probabilities(loaded, x[:5], np)
                if not np.allclose(expected, restored, rtol=0, atol=1e-12):
                    raise RuntimeError("Prediksi model berubah setelah disimpan/dimuat")
                write_json(path/"feature_columns.json", bundle["features"])
                write_json(path/"model_metadata.json", {
                    "algorithm": name, "parameters": params, "classes": CLASSES,
                    "class_names": NAMES, "features": bundle["features"],
                    "thresholds": bundle["thresholds"], "training_rows": len(development),
                    "training_start": development[0]["Date"], "training_end": development[-1]["Date"],
                    "fit_seconds": refit_seconds, "serialization_check": "passed",
                    "status": "exploratory_development_refit_not_production_approved", "model_ready": False,
                    "input_hashes": bundle["input_hashes"], "package_versions": versions,
                    "python_version": platform.python_version(), "script_sha256": sha256(__file__)})
                write_csv(path/"feature_importance.csv",
                          [{"Feature": c, "Importance": float(v)}
                           for c,v in zip(bundle["features"], model.feature_importances_)],
                          ["Feature", "Importance"])
        chosen = None if smoke else select_baseline(summaries, config["selection"]["macro_f1_tolerance"])
        if any(sha256(bundle["root"]/n) != checksum for n, checksum in bundle["input_hashes"].items()):
            raise RuntimeError("Masukan berubah selama training")
        summary = {"status": "completed_smoke_only" if smoke else "completed_exploratory_baseline",
                   "mode": "smoke" if smoke else "baseline", "model_ready": False,
                   "test_read": False, "test_evaluated": False, "tuning_performed": False,
                   "candidate_ablation_performed": False, "models": results,
                   "selected_baseline_on_validation": chosen,
                   "selection_scope": "baseline_only_not_final_research_model",
                   "selection_rule": config["selection"], "features": bundle["features"],
                   "thresholds": bundle["thresholds"], "input_hashes": bundle["input_hashes"],
                   "source_feature_file": bundle["metadata"].get("input_file"),
                   "source_feature_sha256": bundle["metadata"].get("input_sha256"),
                   "source_preprocessing_file": bundle["metadata"].get("preprocessing_file"),
                   "source_preprocessing_sha256": bundle["metadata"].get("preprocessing_sha256"),
                   "script_sha256": sha256(__file__), "python_version": platform.python_version(),
                   "machine": platform.machine(), "package_versions": versions,
                   "elapsed_seconds": time.perf_counter()-start_run,
                   "std_convention": "sample standard deviation ddof=1 across five folds",
                   "undefined_macro_policy": "null if any class metric is undefined; see per-fold reasons",
                   "limitations": bundle["metadata"]["limitations"]}
        write_json(out/"summary.json", summary)
        write_json(out/"run_status.json", {"status": "completed", "mode": summary["mode"]})
        table = []
        def fmt(value):
            return "n/a" if value is None else f"{value:.4f}"
        def percent(value):
            return "n/a" if value is None else f"{value * 100:.2f}%"
        comparison = []
        for name, stats in summaries.items():
            table.append(f"| {name} | {percent(stats['accuracy']['mean'])} | {fmt(stats['macro_f1']['mean'])} | {fmt(stats['macro_f1']['std'])} | {percent(stats['recall_bearish']['mean'])} |")
            pooled = results[name]["pooled_validation"]
            comparison.append({
                "Model": name, "MeanValidationAccuracy": stats["accuracy"]["mean"],
                "StdValidationAccuracy": stats["accuracy"]["std"],
                "MeanMacroF1": stats["macro_f1"]["mean"], "StdMacroF1": stats["macro_f1"]["std"],
                "MeanRecallBearish": stats["recall_bearish"]["mean"],
                "ValidationRows": pooled["rows"], "PooledValidationAccuracy": pooled["accuracy"],
                "CorrectValidationPredictions": sum(pooled["confusion_matrix"][i][i] for i in CLASSES),
            })
        write_csv(out/"model_comparison.csv", comparison, list(comparison[0]))
        (out/"HASIL_TRAINING.md").write_text(
            "# Hasil training baseline\n\n"
            f"Mode: {summary['mode']}. CPU, {config['jobs']} thread, {config['trees']} boosting rounds.\n\n"
            "| Model | Mean Accuracy validation | Mean Macro F1 | Std Macro F1 | Mean Recall Bearish |\n"
            "|---|---:|---:|---:|---:|\n"+"\n".join(table)+"\n\n"
            "Setiap algoritma mempunyai accuracy sendiri: jumlah prediksi regime yang benar "
            "dibagi jumlah prediksi pada validation. Tabel menampilkan rata-rata sederhana "
            "lima fold yang sama untuk kedua algoritma. Angka dalam JSON/CSV disimpan "
            "pada skala 0–1; tampilan accuracy dan Recall Bearish memakai persen.\n\n"
            "Accuracy gabungan seluruh prediksi validation tersimpan sebagai pooled_validation "
            "pada summary.json dan PooledValidationAccuracy pada model_comparison.csv. "
            "Nilainya dapat sedikit berbeda dari mean karena ukuran fold tidak persis sama.\n\n"
            f"Pilihan baseline berdasarkan validation: {chosen or 'tidak dipilih pada smoke test'}. "
            "Std menggunakan ddof=1. Nilai n/a berarti metrik tidak terdefinisi.\n\n"
            "CSV final test tidak dibaca/dievaluasi. Tidak ada tuning atau seleksi kandidat tambahan. "
            "Model development adalah hasil refit untuk eksplorasi. Hasil mewarisi temuan "
            "kalender, Volume, serta waktu tersedia makro; belum untuk klaim "
            "performa akhir atau penggunaan produksi. Rincian ada di summary.json.\n",
            encoding="utf-8")
        print(f"Selesai. Hasil: {out}", flush=True)
        return summary
    except KeyboardInterrupt:
        write_json(out/"run_status.json", {"status": "interrupted", "mode": "smoke" if smoke else "baseline"})
        raise
    except Exception as exc:
        write_json(out/"run_status.json", {"status": "failed", "error": str(exc)})
        raise


def main(argv=None):
    # 4. Setiap run mendapat folder baru; parameter CLI hanya mengubah konfigurasi run.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE/"config_training.json")
    parser.add_argument("--check-data", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="20 boosting rounds, lima fold, tanpa seleksi pemenang")
    parser.add_argument("--trees", type=int)
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--models", nargs="+", choices=["xgboost", "lightgbm"])
    parser.add_argument("--output-dir", type=Path, help="Direktori baru; tidak boleh sudah ada")
    args = parser.parse_args(argv)
    config_path = args.config.resolve()
    config = read_json(config_path)
    config["trees"] = args.trees if args.trees is not None else 20 if args.smoke else config["trees"]
    config["jobs"] = args.jobs if args.jobs is not None else config["jobs"]
    config["models"] = args.models or config["models"]
    if args.smoke and args.trees is not None:
        parser.error("--smoke selalu memakai 20 rounds; --trees digunakan untuk baseline biasa")
    if (not isinstance(config["trees"], int) or not isinstance(config["jobs"], int)
            or config["trees"] < 1 or config["jobs"] < 1 or not config["models"]
            or not set(config["models"]) <= {"xgboost", "lightgbm"}
            or len(set(config["models"])) != len(config["models"])):
        parser.error("Trees/jobs harus positif dan daftar model tidak boleh duplikat")
    tolerance = config["selection"]["macro_f1_tolerance"]
    if not math.isfinite(tolerance) or tolerance < 0:
        parser.error("Toleransi Macro F1 harus finite dan tidak negatif")
    config["config_source_sha256"] = sha256(config_path)
    # Ambil data dari path konfigurasi, periksa checksum, kelengkapan fitur,
    # urutan waktu, dan purge gap sebelum training dijalankan.
    bundle = load_bundle(config, config_path.parent)
    if args.check_data:
        print(json.dumps({"status": "passed", "features": bundle["features"],
                          "folds": [{"fold": f["fold"], "train": len(f["train"]),
                                     "validation": len(f["validation"])} for f in bundle["folds"]],
                          "development_train_rows": len(bundle["development"]),
                          "test_read": False, "model_ready": False}, indent=2))
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    out = args.output_dir.resolve() if args.output_dir else HERE/"runs"/f"{'smoke' if args.smoke else 'baseline'}_{stamp}"
    if out.exists():
        parser.error("Folder output sudah ada; pilih folder baru agar hasil lama tidak tertimpa")
    run_training(config, bundle, out, args.smoke)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Training dihentikan. Jalankan ulang untuk membuat folder hasil baru.", file=sys.stderr)
        sys.exit(130)
    except (ValueError, RuntimeError, FileNotFoundError, KeyError) as error:
        print(f"GAGAL: {error}", file=sys.stderr)
        sys.exit(1)
