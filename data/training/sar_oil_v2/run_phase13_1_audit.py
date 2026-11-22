import csv
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, "backend")

from app.vision.sar_detector import SARDarkFormationDetector
from app.vision.sar_detector_v2 import SAROilSlickDetectorV2
from app.vision.wind_screener import (
    ScreeningStatus,
    WindAwareSARScreener,
    WindClassification,
)
from app.vision.era5_client import LocalERA5Cache, ERA5Service

data_dir = Path("data/training/sar_oil_v2")
img_dir = data_dir / "images"
cache_path = Path("data/cache/era5_wind_cache.json")
p12_manifest_path = data_dir / "sar_splits_v2_2_clean_manifest.json"
p13_manifest_path = data_dir / "sar_splits_phase13_manifest.json"
output_report_path = Path("data/models/sar/v2_2_scene_clean/phase13_1_audit_report.json")
output_csv_path = Path("data/models/sar/v2_2_scene_clean/phase13_1_per_sample_audit.csv")

print("=" * 80)
print("PHASE 13.1: WIND-AWARE SAR INTELLIGENCE AUDIT & THREE-STATE EVALUATION")
print("=" * 80)

# 1. Load manifests
with open(p12_manifest_path, "r", encoding="utf-8") as f:
    p12_manifest = json.load(f)
    p12_test_items = p12_manifest["splits"]["test"]

with open(p13_manifest_path, "r", encoding="utf-8") as f:
    p13_manifest = json.load(f)
    env_dev_items = p13_manifest["splits"]["env_dev"]
    env_val_items = p13_manifest["splits"]["env_val"]
    locked_test_items = p13_manifest["splits"]["locked_final_test"]

print(f"Loaded splits: P12 Test={len(p12_test_items)}, Dev={len(env_dev_items)}, Val={len(env_val_items)}, Locked Test={len(locked_test_items)}")

# 2. Initialize Models & Screener
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

era5_service = ERA5Service(cache_path=cache_path)
screener = WindAwareSARScreener(
    detector=v2_2_detector,
    era5_service=era5_service,
    low_wind_threshold_ms=3.0,
    high_wind_threshold_ms=12.0,
)

def evaluate_and_audit(split_name, items):
    print(f"\nProcessing {split_name} (n={len(items)})...")
    records = []

    for item in items:
        img_name = item["image"]
        img_path = img_dir / img_name
        y_true = item["label"]
        cluster = item.get("cluster", "oil" if y_true == 1 else "unknown")
        subset = item.get("subset", "ow")
        comp_id = item.get("component_id") or "NA"
        safe_scene = item.get("raw_scene") or (item.get("safes", [""])[0] if item.get("safes") else "NA")

        # 1. Baseline V1
        with Image.open(img_path) as im:
            im_arr = np.array(im.convert("L"))
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
        v1_res = v1_detector.predict(v1_payload)
        v1_pred = 1 if (v1_res and v1_res[0].signature.value in ("oil_like_signature", "dark_formation")) else 0

        # 2. V2.1
        v2_1_res = v2_1_detector.predict(img_path)
        v2_1_p = v2_1_res[0].extra["p_oil_candidate"] if v2_1_res else 0.0
        v2_1_pred = 1 if v2_1_p >= 0.50 else 0

        # 3. V2.2
        v2_2_res = v2_2_detector.predict(img_path)
        v2_2_p = v2_2_res[0].extra["p_oil_candidate"] if v2_2_res else 0.0
        v2_2_pred = 1 if v2_2_p >= 0.50 else 0

        # 4. Wind Screener
        screen_res = screener.screen(
            img_path,
            latitude=item.get("center_lat"),
            longitude=item.get("center_lon"),
            timestamp_iso=item.get("start_time"),
            is_coastal=item.get("is_coastal", False),
            patch_id=img_name,
        )

        wind_ctx = screen_res["wind_context"]
        w_speed = wind_ctx.get("wind_speed_ms")
        w_class = wind_ctx.get("classification")
        final_status = screen_res["final_screening_status"]
        retained = screen_res["retained_for_analyst_review"]

        # Three-state designation:
        # A. CANDIDATE_REQUIRES_REVIEW (CNN positive + wind normal / unflagged)
        # B. LOW_WIND_AMBIGUITY_REVIEW (CNN positive + low wind < 3 m/s)
        # C. NO_CANDIDATE_DETECTED (CNN negative)
        flagged_for_review = (final_status == ScreeningStatus.LOW_WIND_AMBIGUITY_REVIEW.value)

        # Formulate explicit rationale
        if final_status == ScreeningStatus.NO_CANDIDATE_DETECTED.value:
            reason = f"CNN did not detect oil candidate (p_oil={v2_2_p:.4f} < 0.50)."
        elif final_status == ScreeningStatus.LOW_WIND_AMBIGUITY_REVIEW.value:
            reason = f"CNN detected candidate (p_oil={v2_2_p:.4f}), but ERA5 wind ({w_speed:.2f} m/s < 3.0 m/s) indicates natural look-alike ambiguity. Retained for analyst review."
        elif final_status == ScreeningStatus.HIGH_WIND_AMBIGUITY_REVIEW.value:
            reason = f"CNN detected candidate (p_oil={v2_2_p:.4f}), but ERA5 wind ({w_speed:.2f} m/s > 12.0 m/s) suggests rapid dispersion. Retained for analyst review."
        elif final_status == ScreeningStatus.CANDIDATE_REQUIRES_REVIEW.value:
            if w_class == WindClassification.UNKNOWN.value:
                reason = f"CNN detected candidate (p_oil={v2_2_p:.4f}). ERA5 wind unavailable; retained without environmental gating."
            else:
                reason = f"CNN detected candidate (p_oil={v2_2_p:.4f}) and ERA5 wind ({w_speed:.2f} m/s) is diagnostic (3-12 m/s). Retained for standard review."
        else:
            reason = f"Status: {final_status}"

        # Historical Phase 13 binary suppression behavior:
        # A candidate was 1 if screened_status == 'candidate_screened_positive', else 0
        # Under Phase 13 logic:
        # if p >= 0.25 and wind in range -> 1; else 0
        p13_binary_suppressed_pred = 1 if (v2_2_res and v2_2_res[0].signature.value in ("oil_like_signature", "dark_formation") and w_speed is not None and 3.0 <= w_speed <= 12.0) else 0

        # Strict clean binary suppression (CNN >= 0.50 AND wind >= 3.0 m/s):
        clean_binary_pred = 1 if (v2_2_pred == 1 and w_speed is not None and 3.0 <= w_speed <= 12.0) else 0

        records.append({
            "split": split_name,
            "image": img_name,
            "ground_truth": y_true,
            "subset": subset,
            "cluster": cluster,
            "component_id": comp_id,
            "safe_scene": safe_scene,
            "v1_pred": v1_pred,
            "v2_1_pred": v2_1_pred,
            "v2_1_p_oil": round(v2_1_p, 4),
            "v2_2_pred": v2_2_pred,
            "v2_2_p_oil": round(v2_2_p, 4),
            "wind_speed_ms": w_speed,
            "wind_direction_deg": wind_ctx.get("wind_direction_degrees"),
            "wind_classification": w_class,
            "screening_status": final_status,
            "retained_for_analyst_review": retained,
            "flagged_for_review": flagged_for_review,
            "p13_binary_screened_pred": p13_binary_suppressed_pred,
            "clean_binary_screened_pred": clean_binary_pred,
            "reason": reason,
            "is_coastal": item.get("is_coastal", False),
        })

    def calc_metrics(y_trues, y_preds):
        tp = sum(1 for yt, yp in zip(y_trues, y_preds) if yt == 1 and yp == 1)
        fp = sum(1 for yt, yp in zip(y_trues, y_preds) if yt == 0 and yp == 1)
        tn = sum(1 for yt, yp in zip(y_trues, y_preds) if yt == 0 and yp == 0)
        fn = sum(1 for yt, yp in zip(y_trues, y_preds) if yt == 1 and yp == 0)
        tot = len(y_trues)
        acc = (tp + tn) / tot if tot else 0.0
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
    m_p13_binary = calc_metrics(y_t, [r["p13_binary_screened_pred"] for r in records])
    m_clean_binary = calc_metrics(y_t, [r["clean_binary_screened_pred"] for r in records])

    # Three-state review counts
    n_candidates_retained = sum(1 for r in records if r["retained_for_analyst_review"])
    n_low_wind_flagged = sum(1 for r in records if r["flagged_for_review"])
    n_true_oil_retained = sum(1 for r in records if r["ground_truth"] == 1 and r["retained_for_analyst_review"])
    n_true_oil_flagged = sum(1 for r in records if r["ground_truth"] == 1 and r["flagged_for_review"])
    n_true_oil_standard = sum(1 for r in records if r["ground_truth"] == 1 and r["screening_status"] == ScreeningStatus.CANDIDATE_REQUIRES_REVIEW.value)
    n_la_flagged = sum(1 for r in records if r["ground_truth"] == 0 and r["flagged_for_review"])
    n_la_incorrectly_retained = sum(1 for r in records if r["ground_truth"] == 0 and r["screening_status"] == ScreeningStatus.CANDIDATE_REQUIRES_REVIEW.value)
    n_missed_slicks = sum(1 for r in records if r["ground_truth"] == 1 and not r["retained_for_analyst_review"])

    three_state_summary = {
        "total_samples": len(records),
        "total_oil_ground_truth": sum(y_t),
        "total_lookalike_ground_truth": len(y_t) - sum(y_t),
        "candidates_retained": n_candidates_retained,
        "low_wind_candidates_flagged": n_low_wind_flagged,
        "true_oil_slicks_retained_total": n_true_oil_retained,
        "true_oil_slicks_standard_review": n_true_oil_standard,
        "true_oil_slicks_flagged_low_wind": n_true_oil_flagged,
        "lookalikes_flagged_low_wind": n_la_flagged,
        "lookalikes_unflagged_review": n_la_incorrectly_retained,
        "missed_oil_slicks": n_missed_slicks,
        "oil_slick_retention_rate": round(n_true_oil_retained / sum(y_t), 4) if sum(y_t) else 0.0,
        "lookalike_review_flag_rate": round(n_la_flagged / (len(y_t) - sum(y_t)), 4) if (len(y_t) - sum(y_t)) else 0.0,
    }

    print(f"--- Metrics for {split_name} ---")
    print(f"CNN V2.2:     TP={m_v2_2['TP']} FP={m_v2_2['FP']} TN={m_v2_2['TN']} FN={m_v2_2['FN']} Acc={m_v2_2['Accuracy']:.4f} F1={m_v2_2['F1']:.4f}")
    print(f"Phase 13 Bin: TP={m_p13_binary['TP']} FP={m_p13_binary['FP']} TN={m_p13_binary['TN']} FN={m_p13_binary['FN']} Acc={m_p13_binary['Accuracy']:.4f} F1={m_p13_binary['F1']:.4f}")
    print(f"Clean Binary: TP={m_clean_binary['TP']} FP={m_clean_binary['FP']} TN={m_clean_binary['TN']} FN={m_clean_binary['FN']} Acc={m_clean_binary['Accuracy']:.4f} F1={m_clean_binary['F1']:.4f}")
    print(f"Three-State: Retained={n_candidates_retained} (Oil={n_true_oil_retained}, LA={n_la_flagged + n_la_incorrectly_retained}), Flagged Low-Wind={n_low_wind_flagged} (Oil={n_true_oil_flagged}, LA={n_la_flagged})")

    return {
        "metrics": {
            "baseline_v1": m_v1,
            "expanded_v2_1": m_v2_1,
            "scene_clean_v2_2": m_v2_2,
            "phase13_binary_screening": m_p13_binary,
            "clean_binary_screening": m_clean_binary,
        },
        "three_state_summary": three_state_summary,
        "sample_records": records,
    }

# Execute evaluation across all splits
report_p12 = evaluate_and_audit("Benchmark 1 (Phase 12 Held-Out Test Set)", p12_test_items)
report_dev = evaluate_and_audit("Phase 13 Development Set (env_dev)", env_dev_items)
report_val = evaluate_and_audit("Phase 13 Validation Set (env_val)", env_val_items)
report_locked = evaluate_and_audit("Benchmark 2 (Phase 13 Locked Final Test Set)", locked_test_items)

# Combine all records for per-sample audit CSV
all_records = []
all_records.extend(report_p12["sample_records"])
all_records.extend(report_dev["sample_records"])
all_records.extend(report_val["sample_records"])
all_records.extend(report_locked["sample_records"])

# Write CSV
fieldnames = [
    "split", "image", "ground_truth", "subset", "cluster", "component_id", "safe_scene",
    "v1_pred", "v2_1_pred", "v2_1_p_oil", "v2_2_pred", "v2_2_p_oil",
    "wind_speed_ms", "wind_direction_deg", "wind_classification",
    "screening_status", "retained_for_analyst_review", "flagged_for_review",
    "p13_binary_screened_pred", "clean_binary_screened_pred", "reason", "is_coastal"
]
with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for r in all_records:
        writer.writerow(r)
print(f"\nSaved {len(all_records)} auditable per-sample rows to {output_csv_path}")

# Combined Dev+Val report for Policy Validation (Objective 7)
dev_val_records = report_dev["sample_records"] + report_val["sample_records"]
y_t_dv = [r["ground_truth"] for r in dev_val_records]
m_v2_2_dv = {
    "TP": sum(1 for yt, r in zip(y_t_dv, dev_val_records) if yt == 1 and r["v2_2_pred"] == 1),
    "FP": sum(1 for yt, r in zip(y_t_dv, dev_val_records) if yt == 0 and r["v2_2_pred"] == 1),
    "TN": sum(1 for yt, r in zip(y_t_dv, dev_val_records) if yt == 0 and r["v2_2_pred"] == 0),
    "FN": sum(1 for yt, r in zip(y_t_dv, dev_val_records) if yt == 1 and r["v2_2_pred"] == 0),
}
m_p13_bin_dv = {
    "TP": sum(1 for yt, r in zip(y_t_dv, dev_val_records) if yt == 1 and r["p13_binary_screened_pred"] == 1),
    "FP": sum(1 for yt, r in zip(y_t_dv, dev_val_records) if yt == 0 and r["p13_binary_screened_pred"] == 1),
    "TN": sum(1 for yt, r in zip(y_t_dv, dev_val_records) if yt == 0 and r["p13_binary_screened_pred"] == 0),
    "FN": sum(1 for yt, r in zip(y_t_dv, dev_val_records) if yt == 1 and r["p13_binary_screened_pred"] == 0),
}
three_state_dv = {
    "total_samples": 100,
    "oil_ground_truth": sum(y_t_dv),
    "lookalike_ground_truth": 100 - sum(y_t_dv),
    "candidates_retained": sum(1 for r in dev_val_records if r["retained_for_analyst_review"]),
    "low_wind_flagged": sum(1 for r in dev_val_records if r["flagged_for_review"]),
    "true_oil_retained": sum(1 for r in dev_val_records if r["ground_truth"] == 1 and r["retained_for_analyst_review"]),
    "true_oil_flagged": sum(1 for r in dev_val_records if r["ground_truth"] == 1 and r["flagged_for_review"]),
    "lookalikes_flagged": sum(1 for r in dev_val_records if r["ground_truth"] == 0 and r["flagged_for_review"]),
    "lookalikes_retained": sum(1 for r in dev_val_records if r["ground_truth"] == 0 and r["screening_status"] == ScreeningStatus.CANDIDATE_REQUIRES_REVIEW.value),
}

final_audit_report = {
    "audit_timestamp": "2026-11-03T16:50:00Z",
    "audit_version": "13.1.0",
    "benchmarks": {
        "benchmark1_phase12_test": report_p12,
        "phase13_env_dev": report_dev,
        "phase13_env_val": report_val,
        "phase13_combined_dev_val": {
            "v2_2_confusion_matrix": m_v2_2_dv,
            "binary_suppression_confusion_matrix": m_p13_bin_dv,
            "three_state_summary": three_state_dv,
        },
        "benchmark2_phase13_locked_test": report_locked,
    }
}

with open(output_report_path, "w", encoding="utf-8") as f:
    json.dump(final_audit_report, f, indent=2)

print(f"\nFinal Phase 13.1 Audit Report saved to {output_report_path}!")
