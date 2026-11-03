"""Bandingkan Dummy, tuning terbatas, dan kandidat domestik pada fold tersimpan.

Contoh: python tune_models.py --check-data
        python tune_models.py --smoke
        python tune_models.py
Semua pemilihan memakai validation; skrip tidak membuka CSV final test.
"""
from __future__ import annotations

# 1. Kontrak dan pemeriksaan masukan memakai fungsi baseline yang sudah diuji.
import argparse
import copy
import hashlib
import importlib.metadata
import itertools
import json
import math
import platform
import random
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import train_models as base

HERE = Path(__file__).resolve().parent
MODELS = ["xgboost", "lightgbm"]
EXTRAS = {"core": [], "core_plus_bi": ["bi_rate_change"],
          "core_plus_inflation": ["inflation_yoy"],
          "core_plus_both": ["bi_rate_change", "inflation_yoy"]}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def features_for(contract, name):
    """Hanya 13 fitur inti dan dua kandidat yang tercantum dalam rancangan."""
    expected = [*base.CORE, *EXTRAS[name]]
    if contract["feature_sets"][name] != expected:
        raise ValueError(f"Daftar fitur tidak sesuai kontrak: {name}")
    if set(expected) & set(contract["forbidden_input_columns"]):
        raise ValueError("Kandidat memuat kolom yang dilarang")
    return expected


def candidate_available(row, start):
    """Gunakan observasi sesudah pergantian instrumen; tidak mengisi nilai kosong."""
    return row["Date"] >= start and all(
        row.get(column, "") != "" and math.isfinite(float(row[column]))
        for column in EXTRAS["core_plus_both"])


def common_folds(bundle, start):
    """Satu populasi bersama untuk keempat konfigurasi dan kedua algoritma."""
    date.fromisoformat(start)
    if start < "2016-08-19":
        raise ValueError("Kandidat BI-Rate tidak boleh mencampur instrumen sebelum 19 Agustus 2016")
    folds, manifest = [], []
    test_start = bundle["metadata"]["splits_after_purge"]["test"]["start_date"]
    for fold in bundle["folds"]:
        selected = {part: [r for r in fold[part] if candidate_available(r, start)]
                    for part in ["train", "validation"]}
        if not all(selected.values()):
            raise ValueError("Populasi kandidat kosong pada salah satu fold")
        if {r["y_t"] for r in selected["train"]} != set(base.CLASSES):
            raise ValueError("Training kandidat harus memiliki tiga kelas")
        base.validate_boundary(selected["train"], selected["validation"], test_start)
        folds.append({"fold": fold["fold"], **selected})
        stats = {"fold": fold["fold"]}
        for part in ["train", "validation"]:
            rows = selected[part]
            identities = [[r["Date"], r["y_t"], r["label_end_date"]] for r in rows]
            stats[part] = {"rows": len(rows), "start": rows[0]["Date"],
                           "end": rows[-1]["Date"], "removed": len(fold[part])-len(rows),
                           "dates_labels_sha256": fingerprint(identities)}
        manifest.append(stats)
    return folds, manifest


# 2. Seluruh percobaan disusun dan disimpan sebelum skor validation dihitung.
def trial_plan(baseline, settings, count, smoke):
    allowed = {
        "xgboost": {"n_estimators", "learning_rate", "max_depth", "min_child_weight",
                    "subsample", "colsample_bytree", "reg_lambda"},
        "lightgbm": {"n_estimators", "learning_rate", "max_depth", "num_leaves",
                    "min_child_samples", "subsample", "colsample_bytree", "reg_lambda"}}
    plan = {}
    for index, name in enumerate(MODELS):
        original = {**baseline[name], "n_estimators": 20 if smoke else baseline["trees"],
                    "n_jobs": baseline["jobs"], "random_state": baseline["seed"]}
        space = settings["search_spaces"][name]
        if set(space) != allowed[name] or any(not isinstance(v, list) or not v for v in space.values()):
            raise ValueError(f"Ruang tuning tidak valid: {name}")
        keys = sorted(space)
        choices = []
        for values in itertools.product(*(space[k] for k in keys)):
            delta = dict(zip(keys, values))
            if (any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0
                    for v in delta.values()) or delta["subsample"] > 1
                    or delta["colsample_bytree"] > 1):
                raise ValueError("Nilai ruang tuning harus finite dan dalam rentang yang sah")
            if any(not isinstance(delta[k], int) for k in
                   (["n_estimators", "max_depth", "min_child_weight"] if name == "xgboost"
                    else ["n_estimators", "max_depth", "num_leaves", "min_child_samples"])):
                raise ValueError("Parameter hitungan harus berupa bilangan bulat")
            if name == "lightgbm" and delta["num_leaves"] > 2**delta["max_depth"]:
                continue
            # Pada LightGBM, subsample baru aktif bila frekuensi bagging positif.
            if name == "lightgbm":
                delta["subsample_freq"] = 1 if delta["subsample"] < 1 else 0
            if smoke:
                delta["n_estimators"] = 20
            params = {**original, **delta}
            if params != original:
                choices.append(params)
        unique = {fingerprint(p): p for p in choices}
        choices = [unique[key] for key in sorted(unique)]
        if count < 1 or count > len(choices):
            raise ValueError("Jumlah percobaan harus positif dan tidak melampaui ruang unik")
        sampled = random.Random(baseline["seed"]+index).sample(choices, count)
        plan[name] = [{"id": "baseline", "parameters": original}]
        plan[name] += [{"id": f"trial_{i:02d}", "parameters": p}
                       for i, p in enumerate(sampled, 1)]
    return plan


def select_shared(candidates):
    """Tambahan harus lolos pada kedua algoritma; aturan ditetapkan sebelum run."""
    eligible, decisions = [], {}
    for name in EXTRAS:
        if name == "core":
            continue
        checks = {}
        for model in MODELS:
            reference = candidates[model]["core"]["summary"]
            score = candidates[model][name]["summary"]
            checks[model] = (
                score["macro_f1"]["mean"] is not None
                and score["recall_bearish"]["mean"] is not None
                and score["macro_f1"]["mean"] > reference["macro_f1"]["mean"]
                and score["recall_bearish"]["mean"] >= reference["recall_bearish"]["mean"])
        decisions[name] = checks
        if all(checks.values()):
            eligible.append(name)
    # Peringkat bersama: mean Macro F1 kedua algoritma, lalu lebih sedikit fitur.
    selected = min(eligible, key=lambda name: (
        -sum(candidates[m][name]["summary"]["macro_f1"]["mean"] for m in MODELS)/2,
        len(EXTRAS[name]), name)) if eligible else "core"
    return selected, decisions


# 3. Evaluasi manual mempertahankan fold/purge asli; validation tidak masuk fit.
def classifier(name, params, modules):
    if name == "dummy":
        from sklearn.dummy import DummyClassifier
        return DummyClassifier(strategy="most_frequent")
    cls = modules[name].XGBClassifier if name == "xgboost" else modules[name].LGBMClassifier
    return cls(**params)


def evaluate(name, params, folds, features, modules, path):
    np = modules["numpy"]
    scores, train_scores, predictions = [], [], []
    start = time.perf_counter()
    for fold in folds:
        training, validation = fold["train"], fold["validation"]
        x_train, x_val = (base.matrix(rows, features, np) for rows in [training, validation])
        y_train = np.asarray([r["y_t"] for r in training], dtype=int)
        model = classifier(name, params, modules)
        began = time.perf_counter()
        model.fit(x_train, y_train)
        fit_seconds = time.perf_counter()-began
        proba, predicted = base.probabilities(model, x_val, np)
        _, train_predicted = base.probabilities(model, x_train, np)
        score = base.metrics([r["y_t"] for r in validation], predicted)
        train_score = base.metrics(y_train.tolist(), train_predicted)
        scores.append(score)
        train_scores.append(train_score)
        majority = int(np.argmax(np.bincount(y_train, minlength=3)))
        base.write_json(path/f"fold_{fold['fold']}"/"metrics.json", {
            **score, "fit_seconds": fit_seconds, "training_metrics": train_score,
            "train_rows": len(training), "train_start": training[0]["Date"],
            "train_end": training[-1]["Date"], "validation_start": validation[0]["Date"],
            "validation_end": validation[-1]["Date"], "training_majority_class": majority,
            "parameters": params, "features": features})
        base.write_csv(path/f"fold_{fold['fold']}"/"confusion_matrix.csv", [
            {"Actual": label, **dict(zip(base.NAMES, score["confusion_matrix"][i]))}
            for i, label in enumerate(base.NAMES)], ["Actual", *base.NAMES])
        for row, probs, pred in zip(validation, proba, predicted):
            predictions.append({"Fold": fold["fold"], "Date": row["Date"],
                "label_end_date": row["label_end_date"], "y_true": row["y_t"], "y_pred": pred,
                **{f"p_{label.lower()}": float(probs[i]) for i, label in enumerate(base.NAMES)}})
    base.write_csv(path/"validation_predictions.csv", predictions, list(predictions[0]))
    summary = base.summarize(scores)
    train_summary = base.summarize(train_scores)
    result = {"summary": summary, "training_summary": train_summary,
              "fold_metrics": scores, "parameters": params,
              "features": features, "validation_rows": len(predictions),
              "pooled_validation": base.metrics([r["y_true"] for r in predictions],
                                                 [r["y_pred"] for r in predictions]),
              "elapsed_seconds": time.perf_counter()-start}
    base.write_json(path/"result.json", result)
    return result


def score_row(phase, model, trial, result, selected=False):
    summary = result["summary"]
    return {"Phase": phase, "Model": model, "Trial": trial, "Selected": selected,
            "MeanMacroF1": summary["macro_f1"]["mean"],
            "StdMacroF1": summary["macro_f1"]["std"],
            "MeanAccuracy": summary["accuracy"]["mean"],
            "MeanRecallBearish": summary["recall_bearish"]["mean"],
            "MeanTrainingAccuracy": result["training_summary"]["accuracy"]["mean"],
            "ValidationRows": result["validation_rows"]}


# 4. Refit menyimpan model eksperimen dan metadata untuk langkah berikutnya.
def refit(name, params, rows, features, modules, bundle, out, versions, population):
    np, joblib = modules["numpy"], modules["joblib"]
    if not rows or max(r["label_end_date"] for r in rows) >= bundle["metadata"]["splits_after_purge"]["test"]["start_date"]:
        raise ValueError("Development refit kosong atau label menyentuh final test")
    x = base.matrix(rows, features, np)
    model = classifier(name, params, modules)
    began = time.perf_counter()
    model.fit(x, np.asarray([r["y_t"] for r in rows], dtype=int))
    seconds = time.perf_counter()-began
    path = out/name/"development_model"
    path.mkdir(parents=True)
    joblib.dump(model, path/"model.joblib")
    loaded = joblib.load(path/"model.joblib")
    expected, _ = base.probabilities(model, x[:5], np)
    restored, _ = base.probabilities(loaded, x[:5], np)
    if not np.allclose(expected, restored, atol=1e-12, rtol=0):
        raise RuntimeError("Artefak model gagal uji simpan/muat")
    metadata = {"algorithm": name, "parameters": params, "features": features,
        "classes": base.CLASSES, "class_names": base.NAMES,
        "thresholds": bundle["thresholds"], "population": population,
        "training_rows": len(rows), "training_start": rows[0]["Date"],
        "training_end": rows[-1]["Date"], "fit_seconds": seconds,
        "serialization_check": "passed", "model_ready": False,
        "status": "exploratory_development_refit_not_production_approved",
        "package_versions": versions, "python_version": platform.python_version(),
        "input_hashes": bundle["input_hashes"], "script_sha256": base.sha256(__file__)}
    base.write_json(path/"model_metadata.json", metadata)
    base.write_json(path/"feature_columns.json", features)
    base.write_csv(path/"feature_importance.csv", [
        {"Feature": f, "Importance": float(v)} for f, v in zip(features, model.feature_importances_)],
        ["Feature", "Importance"])
    return metadata


def report(out, summary):
    def fmt(value):
        return "n/a" if value is None else f"{value:.4f}"

    def table(rows):
        lines = ["| Model / konfigurasi | Mean Macro F1 | Std | Mean Accuracy validation | Mean Recall Bearish | Mean Accuracy training |",
                 "|---|---:|---:|---:|---:|---:|"]
        for label, result in rows:
            s = result["summary"]
            lines.append(f"| {label} | {fmt(s['macro_f1']['mean'])} | {fmt(s['macro_f1']['std'])} | "
                         f"{fmt(s['accuracy']['mean'])} | {fmt(s['recall_bearish']['mean'])} | "
                         f"{fmt(result['training_summary']['accuracy']['mean'])} |")
        return "\n".join(lines)

    rows = [("Dummy mayoritas", summary["dummy_full"])]
    for name in MODELS:
        rows += [(f"{name} baseline", summary["tuning"][name]["baseline"]),
                 (f"{name} tuning", summary["tuning"][name][summary['best_trials'][name]])]
    text = ["# Hasil pembanding tuning dan kandidat fitur", "",
        f"Mode: {summary['mode']}. Metrik berasal dari lima fold validation yang dipakai untuk seleksi.",
        "Skor ini adalah estimasi development; final test belum dievaluasi. Model tetap eksperimen awal.",
        "", "## Pembanding dan tuning fitur inti pada periode penuh", "", table(rows), "",
        f"Percobaan terpilih: {summary['best_trials']}. Pemilihan memakai mean Macro F1, "
        f"toleransi {summary['selection_rule']['macro_f1_tolerance']} lalu std sampel lebih kecil dan accuracy lebih tinggi.", "",
        "Angka pada tabel berskala 0–1; kalikan 100 untuk persen. Accuracy training hanya untuk diagnosis, "
        "bukan ukuran keberhasilan pada data baru. Mean antar-fold berbeda dari skor seluruh prediksi yang digabung. "
        "Rincian kedua jenis skor ada di JSON.",
        "Dummy mempelajari kelas mayoritas hanya dari training setiap fold.", "",
        "## Empat konfigurasi pada periode kandidat bersama", "",
        "Training dimulai pada observasi kandidat lengkap sejak pergantian instrumen BI pada Agustus 2016. "
        "Semua konfigurasi di bawah memakai tanggal, target, threshold, dan fold identik. "
        "Parameter tiap algoritma ditahan tetap pada pilihan tuning inti. "
        "Pembanding inti di tabel ini memiliki riwayat training lebih pendek daripada baseline penuh di atas.", "",
        table([("Dummy mayoritas bersama", summary["dummy_common"])] + [
            (f"{m} / {f}", summary["candidates"][m][f]) for m in MODELS for f in EXTRAS]), "",
        f"Konfigurasi fitur bersama terpilih: **{summary['shared_feature_set']}**. "
        "Kandidat harus meningkatkan mean Macro F1 tanpa menurunkan mean Recall Bearish pada kedua algoritma. "
        "Jika lebih dari satu lolos, gunakan mean Macro F1 gabungan kedua algoritma lalu jumlah fitur lebih sedikit.",
        "", "## Pilihan development dan target accuracy", "",
        f"Model pilihan development: **{summary['selected_development_model']}**; "
        f"populasi: **{summary['selected_population']}**.",
        f"Accuracy target {summary['accuracy_target']:.0%}; mean accuracy pilihan development "
        f"{summary['selected_mean_accuracy']:.2%}; tercapai: **{summary['accuracy_target_reached']}**.",
        "Target 70% dilaporkan sebagai sasaran, tidak digunakan mengubah label atau menghentikan pencarian secara oportunistis.",
        "Mode smoke hanya memeriksa alur dan tidak menghasilkan pilihan model penelitian.", "",
        "## Artefak dan batas penggunaan", "",
        "`leaderboard.csv`: seluruh percobaan; `protocol.json`: ruang/daftar percobaan sebelum skor dilihat; "
        "`common_population.json`: jumlah/tanggal serta hash populasi kandidat. "
        "Setiap percobaan menyimpan prediksi validation, confusion matrix dan skor training/validation tiap fold. "
        "`selected_models/` menyimpan dua model development pada fitur/populasi bersama yang dipilih.", "",
        "Hasil mewarisi catatan kalender, Volume, seri kurs campuran, serta waktu ketersediaan makro. "
        "Periode kandidat adalah pembatasan eksperimen, bukan verifikasi sumber atau waktu rilis historis."]
    (out/"HASIL_EKSPERIMEN.md").write_text("\n\n".join(text)+"\n", encoding="utf-8")


# 5. Orkestrasi menjalankan anggaran tetap dan mempertahankan hasil baseline lama.
def run(baseline, settings, bundle, plan, common, manifest, contract, out, smoke):
    modules = base.dependencies(MODELS)
    versions = {n: importlib.metadata.version(n) for n in
                ["numpy", "scipy", "scikit-learn", "joblib", *MODELS]}
    out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    base.write_json(out/"run_status.json", {"status": "running"})
    base.write_json(out/"protocol.json", {"created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "smoke" if smoke else "development", "baseline_config": baseline,
        "settings": settings, "trial_plan": plan, "features": contract["feature_sets"],
        "thresholds": bundle["thresholds"], "input_hashes": bundle["input_hashes"],
        "package_versions": versions, "python_version": platform.python_version(),
        "tuning_script_sha256": base.sha256(__file__), "baseline_script_sha256": base.sha256(base.__file__),
        "selection": "mean_macro_f1_then_tolerance_std_accuracy_id",
        "candidate_rule": "strict_macro_f1_improvement_and_non_decreasing_recall_for_both_algorithms",
        "candidate_ranking": "mean_macro_f1_across_algorithms_then_fewer_extra_features_then_name",
        "common_parameters": "reuse_each_algorithm_selected_core_parameters_without_additional_tuning",
        "dummy_strategy": "most_frequent_fit_on_training_only", "test_read": False})
    base.write_json(out/"common_population.json", manifest)
    leaderboard, tuning, best, candidates = [], {}, {}, {}
    try:
        dummy_full = evaluate("dummy", {}, bundle["folds"], bundle["features"], modules, out/"dummy_full")
        dummy_common = evaluate("dummy", {}, common, bundle["features"], modules, out/"dummy_common")
        leaderboard += [score_row("full", "dummy", "most_frequent", dummy_full),
                        score_row("common", "dummy", "most_frequent", dummy_common)]
        print("Dummy selesai; memulai anggaran tuning tetap.", flush=True)
        for name in MODELS:
            tuning[name] = {}
            for i, trial in enumerate(plan[name], 1):
                result = evaluate(name, trial["parameters"], bundle["folds"], bundle["features"],
                                  modules, out/"tuning"/name/trial["id"])
                tuning[name][trial["id"]] = result
                s = result["summary"]
                print(f"[{name}] {i}/{len(plan[name])} {trial['id']}: "
                      f"Macro F1={s['macro_f1']['mean']:.4f}, accuracy={s['accuracy']['mean']:.4f}, "
                      f"Recall Bearish={s['recall_bearish']['mean']:.4f}", flush=True)
            best[name] = base.select_baseline({key: r["summary"] for key,r in tuning[name].items()},
                                             baseline["selection"]["macro_f1_tolerance"])
            leaderboard += [score_row("tuning_full", name, key, result, key == best[name])
                            for key,result in tuning[name].items()]
            print(f"[{name}] percobaan terpilih: {best[name]}", flush=True)
        for name in MODELS:
            candidates[name] = {}
            params = tuning[name][best[name]]["parameters"]
            for feature_set in EXTRAS:
                features = features_for(contract, feature_set)
                result = evaluate(name, params, common, features, modules,
                                  out/"candidates"/name/feature_set)
                candidates[name][feature_set] = result
                leaderboard.append(score_row("candidate_common", name, feature_set, result))
                print(f"[{name}] kandidat {feature_set}: "
                      f"Macro F1={result['summary']['macro_f1']['mean']:.4f}", flush=True)
        shared, decisions = select_shared(candidates)
        # Jika tak ada kandidat bersama yang lolos, pertahankan baseline penuh 13 fitur.
        population = "full_core" if shared == "core" else "common_candidate_period"
        selected_results = {m: tuning[m][best[m]] if shared == "core" else candidates[m][shared]
                            for m in MODELS}
        winner = base.select_baseline({m:r["summary"] for m,r in selected_results.items()},
                                      baseline["selection"]["macro_f1_tolerance"])
        features = features_for(contract, shared)
        development = bundle["development"] if shared == "core" else [
            r for r in bundle["development"] if candidate_available(r, settings["candidate_start_date"])]
        artifacts = {m: refit(m, tuning[m][best[m]]["parameters"], development, features,
                             modules, bundle, out/"selected_models", versions, population) for m in MODELS}
        if any(base.sha256(bundle["root"]/name) != sha for name,sha in bundle["input_hashes"].items()):
            raise RuntimeError("Masukan berubah selama eksperimen")
        selected_accuracy = selected_results[winner]["summary"]["accuracy"]["mean"]
        summary = {"status": "completed_smoke_only" if smoke else "completed_exploratory_development",
            "mode": "smoke" if smoke else "development", "model_ready": False,
            "tuning": tuning, "best_trials": best, "dummy_full": dummy_full,
            "dummy_common": dummy_common, "candidates": candidates,
            "candidate_acceptance": decisions, "shared_feature_set": shared,
            "selected_development_model": None if smoke else winner,
            "selected_population": population, "selected_features": features,
            "selected_mean_accuracy": selected_accuracy, "accuracy_target": settings["accuracy_target"],
            "accuracy_target_reached": None if smoke else selected_accuracy >= settings["accuracy_target"],
            "selected_models": artifacts, "input_hashes": bundle["input_hashes"],
            "test_read": False, "test_evaluated": False,
            "validation_scores_used_for_selection": True, "selection_rule": baseline["selection"],
            "candidate_ablation_performed": True, "tuning_performed": True,
            "limitations": bundle["metadata"]["limitations"], "package_versions": versions,
            "elapsed_seconds": time.perf_counter()-started}
        base.write_json(out/"summary.json", summary)
        base.write_csv(out/"leaderboard.csv", leaderboard, list(leaderboard[0]))
        report(out, summary)
        base.write_json(out/"run_status.json", {"status": "completed", "mode": summary["mode"]})
        print(f"Selesai. Hasil: {out}", flush=True)
        return summary
    except BaseException as exc:
        base.write_json(out/"run_status.json", {"status": "interrupted" if isinstance(exc, KeyboardInterrupt)
                                               else "failed", "error": str(exc)})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE/"config_tuning.json")
    parser.add_argument("--trials", type=int, help="Jumlah kombinasi baru per algoritma; default 16")
    parser.add_argument("--check-data", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Dua kombinasi baru, 20 iterasi, seluruh fase")
    parser.add_argument("--output-dir", type=Path, help="Folder baru untuk hasil")
    args = parser.parse_args(argv)
    path = args.config.resolve()
    settings = copy.deepcopy(base.read_json(path))
    config_path = (path.parent/settings["baseline_config"]).resolve()
    baseline = base.read_json(config_path)
    if baseline["models"] != MODELS:
        parser.error("Eksperimen ini membandingkan tepat XGBoost dan LightGBM")
    if (not isinstance(baseline["jobs"], int) or baseline["jobs"] < 1
            or not isinstance(baseline["trees"], int) or baseline["trees"] < 1):
        parser.error("Jobs dan iterasi baseline harus bilangan bulat positif")
    if settings["candidate_consolidation"] != "require_improvement_for_both_algorithms":
        parser.error("Konsolidasi kandidat berbeda dari protokol")
    if not 0 < settings["accuracy_target"] <= 1:
        parser.error("Target accuracy harus dalam (0,1]")
    if args.smoke and args.trials is not None:
        parser.error("--smoke selalu dua kombinasi baru; gunakan --trials pada run utama")
    count = 2 if args.smoke else args.trials if args.trials is not None else settings["random_trials_per_model"]
    if not isinstance(count, int) or count < 1:
        parser.error("Jumlah percobaan harus bilangan bulat positif")
    settings["random_trials_per_model"] = count
    settings["config_sha256"] = base.sha256(path)
    settings["baseline_config_sha256"] = base.sha256(config_path)
    bundle = base.load_bundle(baseline, config_path.parent)
    contract = base.read_json(bundle["root"]/"model_contract.json")
    for name in EXTRAS:
        features_for(contract, name)
    common, manifest = common_folds(bundle, settings["candidate_start_date"])
    plan = trial_plan(baseline, settings, count, args.smoke)
    if args.check_data:
        print(json.dumps({"status": "passed", "new_trials_per_model": count,
            "common_population": manifest, "features": contract["feature_sets"],
            "test_read": False, "model_ready": False}, indent=2))
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    out = args.output_dir.resolve() if args.output_dir else HERE/"runs"/f"{'experiment_smoke' if args.smoke else 'experiments'}_{stamp}"
    if out.exists() or out.is_relative_to(bundle["root"]):
        parser.error("Pilih folder output baru di luar direktori input")
    run(baseline, settings, bundle, plan, common, manifest, contract, out, args.smoke)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Eksperimen dihentikan; run berikutnya membuat folder hasil baru.", file=sys.stderr)
        sys.exit(130)
    except (ValueError, RuntimeError, FileNotFoundError, KeyError) as exc:
        print(f"GAGAL: {exc}", file=sys.stderr)
        sys.exit(1)
