import json
import math
import time
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
import torch
from PIL import Image

from app.vision.sar_detector import SARDarkFormationDetector
from app.vision.sar_detector_v2 import SAROilSlickDetectorV2
from app.vision.wind_screener import (
    WindAwareSARScreener,
    WindClassification,
    ScreeningStatus,
)
from app.vision.era5_client import LocalERA5Cache, ERA5Service

# Setup paths
data_dir = Path("data/training/sar_oil_v2")
img_dir = data_dir / "images"
cache_path = Path("data/cache/era5_wind_cache.json")
p12_manifest_path = data_dir / "sar_splits_v2_2_clean_manifest.json"
p13_manifest_path = data_dir / "sar_splits_phase13_manifest.json"
output_report_path = Path("data/models/sar/v2_2_scene_clean/phase13_evaluation_report.json")

print("=" * 80)
print("PHASE 13: WIND-AWARE SAR INTELLIGENCE EVALUATION BENCHMARK")
print("=" * 80)

# Load manifests
with open(p12_manifest_path, "r", encoding="utf-8") as f:
    p12_test_items = json.load(f)["splits"]["test"]

with open(p13_manifest_path, "r", encoding="utf-8") as f:
    p13_manifest = json.load(f)
    locked_test_items = p13_manifest["splits"]["locked_final_test"]
    env_dev_items = p13_manifest["splits"]["env_dev"]
    env_val_items = p13_manifest["splits"]["env_val"]

print(f"Loaded datasets: P12 Test = {len(p12_test_items)}, Locked Final Test = {len(locked_test_items)}")

# Load models
v1_detector = SARDarkFormationDetector()
v2_1_detector = SAROilSlickDetectorV2(
    model_path="data/models/sar/v2_expanded/best.pt",
    name="sar-oil-slick-v2.1-expanded",
)
v2_2_detector = SAROilSlickDetectorV2(
    model_path="data/models/sar/v2_2_scene_clean/best.pt",
    name="sar-oil-slick-v2.2",
    version="2.2.0-experimental",
)

era5_cache = LocalERA5Cache(cache_path)
era5_service = ERA5Service(cache_path=cache_path)

wind_screener = WindAwareSARScreener(
    detector=v2_2_detector,
    era5_service=era5_service,
    low_wind_threshold_ms=3.0,
    high_wind_threshold_ms=12.0,
)

def evaluate_split(split_name, items):
    print(f"\n=======================================================")
    print(f"BENCHMARKING SPLIT: {split_name} (n={len(items)})")
    print(f"=======================================================")
    
    # Store per-sample predictions
    records = []
    latencies = {"v1": [], "v2_1": [], "v2_2": [], "wind_screener": []}
    
    for item in items:
        img_name = item["image"]
        img_path = img_dir / img_name
        y_true = item["label"]
        cluster = item.get("cluster", "oil" if y_true == 1 else "unknown")
        subset = item.get("subset", "ow")
        
        # 1. Baseline Heuristic V1
        with Image.open(img_path) as im:
            im_arr = np.array(im.convert("L"))
        # Synthetic backscatter dB proxy
        norm = im_arr.astype(float) / 255.0
        db_arr = -35.0 + norm * 30.0
        v1_payload = {
            "region_code": img_name,
            "mean_db": float(np.mean(db_arr)),
            "p10_db": float(np.percentile(db_arr, 10)),
            "p90_db": float(np.percentile(db_arr, 90)),
            "stddev_db": float(np.std(db_arr)),
            "latitude": item.get("center_lat", 33.0),
            "longitude": item.get("center_lon", 33.0),
        }
        t0 = time.perf_counter()
        v1_res = v1_detector.predict(v1_payload)
        latencies["v1"].append((time.perf_counter() - t0) * 1000.0)
        v1_pred = 1 if (v1_res and v1_res[0].signature.value in ("oil_like_signature", "dark_formation")) else 0
        
        # 2. SAR V2.1
        t0 = time.perf_counter()
        v2_1_res = v2_1_detector.predict(img_path)
        latencies["v2_1"].append((time.perf_counter() - t0) * 1000.0)
        v2_1_p = v2_1_res[0].extra["p_oil_candidate"] if v2_1_res else 0.0
        v2_1_pred = 1 if v2_1_p >= 0.50 else 0
        
        # 3. SAR V2.2
        t0 = time.perf_counter()
        v2_2_res = v2_2_detector.predict(img_path)
        latencies["v2_2"].append((time.perf_counter() - t0) * 1000.0)
        v2_2_p = v2_2_res[0].extra["p_oil_candidate"] if v2_2_res else 0.0
        v2_2_pred = 1 if v2_2_p >= 0.50 else 0
        
        # 4. Wind-Aware Screener V2.2
        t0 = time.perf_counter()
        screen_res = wind_screener.screen(
            img_path,
            latitude=item.get("center_lat"),
            longitude=item.get("center_lon"),
            timestamp_iso=item.get("start_time"),
            is_coastal=item.get("is_coastal", False),
            patch_id=img_name,
        )
        latencies["wind_screener"].append((time.perf_counter() - t0) * 1000.0)
        
        wind_ctx = screen_res["wind_context"]
        w_speed = wind_ctx.get("wind_speed_ms")
        w_class = wind_ctx.get("classification")
        screen_status = screen_res["final_screening_status"]
        
        # Operational screening prediction:
        # Screened positive means the candidate satisfies both SAR texture AND physical wind gating
        screened_pred = 1 if screen_status == ScreeningStatus.CANDIDATE_SCREENED_POSITIVE.value else 0
        
        records.append({
            "image": img_name,
            "ground_truth": y_true,
            "subset": subset,
            "cluster": cluster,
            "v1_pred": v1_pred,
            "v2_1_pred": v2_1_pred,
            "v2_1_p_oil": round(v2_1_p, 4),
            "v2_2_pred": v2_2_pred,
            "v2_2_p_oil": round(v2_2_p, 4),
            "wind_speed_ms": w_speed,
            "wind_classification": w_class,
            "screen_status": screen_status,
            "wind_screened_pred": screened_pred,
            "is_coastal": item.get("is_coastal", False),
        })

    def calc_metrics(y_trues, y_preds):
        tp = sum(1 for yt, yp in zip(y_trues, y_preds) if yt == 1 and yp == 1)
        fp = sum(1 for yt, yp in zip(y_trues, y_preds) if yt == 0 and yp == 1)
        tn = sum(1 for yt, yp in zip(y_trues, y_preds) if yt == 0 and yp == 0)
        fn = sum(1 for yt, yp in zip(y_trues, y_preds) if yt == 1 and yp == 0)
        total = len(y_trues)
        acc = (tp + tn) / total if total else 0.0
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        fnr = fn / (fn + tp) if (fn + tp) else 0.0
        return {
            "TP": tp, "FP": fp, "TN": tn, "FN": fn,
            "Accuracy": round(acc, 4),
            "Precision": round(prec, 4),
            "Recall": round(rec, 4),
            "F1": round(f1, 4),
            "FPR": round(fpr, 4),
            "FNR": round(fnr, 4),
        }

    y_t = [r["ground_truth"] for r in records]
    m_v1 = calc_metrics(y_t, [r["v1_pred"] for r in records])
    m_v2_1 = calc_metrics(y_t, [r["v2_1_pred"] for r in records])
    m_v2_2 = calc_metrics(y_t, [r["v2_2_pred"] for r in records])
    m_screen = calc_metrics(y_t, [r["wind_screened_pred"] for r in records])
    
    # McNemar test between V2.2 and Wind-Aware V2.2
    b = sum(1 for r in records if (r["wind_screened_pred"] == r["ground_truth"]) and (r["v2_2_pred"] != r["ground_truth"]))
    c = sum(1 for r in records if (r["v2_2_pred"] == r["ground_truth"]) and (r["wind_screened_pred"] != r["ground_truth"]))
    if b + c > 0:
        chi2 = (abs(b - c) - 1.0) ** 2 / (b + c)
        p_val = round(float(math.erfc(math.sqrt(chi2 / 2.0))), 4)
    else:
        chi2, p_val = 0.0, 1.0

    # Look-alike cluster analysis
    la_clusters = defaultdict(lambda: {"total": 0, "v2_2_fp": 0, "wind_fp": 0, "mean_wind": []})
    for r in records:
        if r["ground_truth"] == 0:
            cl = r["cluster"]
            la_clusters[cl]["total"] += 1
            if r["v2_2_pred"] == 1:
                la_clusters[cl]["v2_2_fp"] += 1
            if r["wind_screened_pred"] == 1:
                la_clusters[cl]["wind_fp"] += 1
            if r["wind_speed_ms"] is not None:
                la_clusters[cl]["mean_wind"].append(r["wind_speed_ms"])

    cluster_report = {}
    for cl, stat in la_clusters.items():
        w_list = stat["mean_wind"]
        cluster_report[cl] = {
            "total_samples": stat["total"],
            "v2_2_false_positives": stat["v2_2_fp"],
            "wind_screened_false_positives": stat["wind_fp"],
            "fp_reduction": stat["v2_2_fp"] - stat["wind_fp"],
            "mean_wind_speed_ms": round(float(np.mean(w_list)), 2) if w_list else None,
        }

    # Wind category breakdown
    wind_cat_breakdown = defaultdict(lambda: {"total": 0, "oil": 0, "la": 0, "v2_2_pos": 0, "screened_pos": 0})
    for r in records:
        wc = r["wind_classification"]
        wind_cat_breakdown[wc]["total"] += 1
        if r["ground_truth"] == 1: wind_cat_breakdown[wc]["oil"] += 1
        else: wind_cat_breakdown[wc]["la"] += 1
        if r["v2_2_pred"] == 1: wind_cat_breakdown[wc]["v2_2_pos"] += 1
        if r["wind_screened_pred"] == 1: wind_cat_breakdown[wc]["screened_pos"] += 1

    print("\n--- 4-MODEL COMPARISON MATRIX ---")
    print(f"{'Model':32s} {'TP':4s} {'FP':4s} {'TN':4s} {'FN':4s} {'Acc':7s} {'Prec':7s} {'Rec':7s} {'F1':7s} {'FPR':7s} {'FNR':7s}")
    print("-" * 88)
    for name, m in [("Baseline Heuristic (v1)", m_v1), ("Expanded SAR V2.1", m_v2_1), ("Scene-Clean SAR V2.2", m_v2_2), ("Wind-Aware Screened V2.2", m_screen)]:
        print(f"{name:32s} {m['TP']:4d} {m['FP']:4d} {m['TN']:4d} {m['FN']:4d} {m['Accuracy']:7.4f} {m['Precision']:7.4f} {m['Recall']:7.4f} {m['F1']:7.4f} {m['FPR']:7.4f} {m['FNR']:7.4f}")

    print(f"\nMcNemar Test (V2.2 vs Wind-Aware Screened): b={b}, c={c}, chi2={chi2:.4f}, p_value={p_val}")

    latency_summary = {
        k: {
            "mean": round(float(np.mean(v)), 2),
            "median": round(float(np.median(v)), 2),
            "p95": round(float(np.percentile(v, 95)), 2),
        }
        for k, v in latencies.items()
    }
    print(f"\nLatency Summary (ms): {latency_summary}")

    return {
        "metrics": {
            "baseline_v1": m_v1,
            "expanded_v2_1": m_v2_1,
            "scene_clean_v2_2": m_v2_2,
            "wind_aware_screened_v2_2": m_screen,
        },
        "mcnemar_test": {
            "b": b,
            "c": c,
            "chi2": round(float(chi2), 4),
            "p_value": p_val,
        },
        "cluster_analysis": cluster_report,
        "wind_category_breakdown": dict(wind_cat_breakdown),
        "latencies_ms": latency_summary,
        "sample_records": records,
    }

# Execute evaluations
report_p12 = evaluate_split("Phase 12 Held-Out Test Set (n=100)", p12_test_items)
report_locked = evaluate_split("Phase 13 Locked Final Test Set (n=100)", locked_test_items)

final_report = {
    "evaluation_date": "2026-11-03T14:45:00Z",
    "benchmarks": {
        "phase12_held_out_test_set": report_p12,
        "phase13_locked_final_test_set": report_locked,
    }
}

with open(output_report_path, "w", encoding="utf-8") as f:
    json.dump(final_report, f, indent=2)

print(f"\nPhase 13 full evaluation report saved to {output_report_path}!")
