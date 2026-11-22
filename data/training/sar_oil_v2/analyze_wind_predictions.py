import json
from collections import defaultdict, Counter
import numpy as np

preds_data = json.load(open("data/models/sar/v2_2_scene_clean/predictions.json"))
cache = json.load(open("data/cache/era5_wind_cache.json"))
p12_manifest = json.load(open("data/training/sar_oil_v2/sar_splits_v2_2_clean_manifest.json"))

test_items = {x["image"]: x for x in p12_manifest["splits"]["test"]}

groups = {"TP": [], "FP": [], "TN": [], "FN": []}

for p in preds_data:
    img = p["image"]
    y_true = p["ground_truth"]  # 1=oil, 0=la
    y_pred = p["pred_v2_2"]     # 1=oil, 0=la
    wind_info = cache.get(img, {})
    w_spd = wind_info.get("wind_speed_ms", None)
    
    item_meta = test_items.get(img, {})
    cluster = item_meta.get("cluster", "unknown")
    subset = item_meta.get("subset", "unknown")
    
    sample_record = {
        "image": img,
        "cluster": cluster,
        "subset": subset,
        "wind_speed": w_spd,
        "wind_dir": wind_info.get("wind_direction_deg"),
        "p_oil": p["prob_v2_2"],
        "is_coastal": wind_info.get("is_coastal", False)
    }
    
    if y_true == 1 and y_pred == 1:
        groups["TP"].append(sample_record)
    elif y_true == 0 and y_pred == 1:
        groups["FP"].append(sample_record)
    elif y_true == 0 and y_pred == 0:
        groups["TN"].append(sample_record)
    elif y_true == 1 and y_pred == 0:
        groups["FN"].append(sample_record)

print(f"Sample Counts: TP={len(groups['TP'])}, FP={len(groups['FP'])}, TN={len(groups['TN'])}, FN={len(groups['FN'])}")

for g_name, g_samples in groups.items():
    spds = [s["wind_speed"] for s in g_samples if s["wind_speed"] is not None]
    low_wind_cnt = sum(1 for s in spds if s < 3.0)
    pct = (low_wind_cnt / len(spds) * 100) if spds else 0.0
    print(f"{g_name:2s} (n={len(g_samples):2d}): Mean Wind={np.mean(spds):.2f} m/s, Median={np.median(spds):.2f} m/s, Min={np.min(spds):.2f}, Max={np.max(spds):.2f}, Under 3 m/s = {low_wind_cnt}/{len(spds)} ({pct:.1f}%)")

print("\n--- DETAILED BREAKDOWN OF THE 21 FALSE POSITIVES ---")
fp_clusters = Counter(s["cluster"] for s in groups["FP"])
print("FP Count by Cluster:", dict(fp_clusters))
print(f"{'Image':25s} {'Cluster':8s} {'Subset':6s} {'Wind (m/s)':11s} {'Direction':10s} {'P(Oil)':8s} {'Coastal':8s}")
print("-" * 80)
for s in sorted(groups["FP"], key=lambda x: x["wind_speed"]):
    print(f"{s['image']:25s} {s['cluster']:8s} {s['subset']:6s} {s['wind_speed']:10.2f}  {s['wind_dir']:8.1f}° {s['p_oil']:7.3f} {str(s['is_coastal']):8s}")

print("\n--- DETAILED BREAKDOWN OF THE 6 FALSE NEGATIVES (MISSED SLICKS) ---")
for s in sorted(groups["FN"], key=lambda x: x["wind_speed"]):
    print(f"{s['image']:25s} {s['cluster']:8s} {s['subset']:6s} {s['wind_speed']:10.2f}  {s['wind_dir']:8.1f}° {s['p_oil']:7.3f} {str(s['is_coastal']):8s}")
