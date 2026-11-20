import json
import random
from pathlib import Path
from collections import defaultdict, Counter

tab_path = Path("data/training/sar_oil_v2/pangaea_980773_annotations.tab")
clean_manifest_path = Path("data/training/sar_oil_v2/sar_splits_v2_2_clean_manifest.json")
p9_path = Path("data/training/sar_oil_v2/sar_splits_manifest.json")
p10_path = Path("data/training/sar_oil_v2/sar_splits_expanded_manifest.json")

with open(clean_manifest_path, "r", encoding="utf-8") as f:
    clean_manifest = json.load(f)

p12_train = set(x["image"] for x in clean_manifest["splits"]["train"])
p12_val = set(x["image"] for x in clean_manifest["splits"]["val"])
p12_test = set(x["image"] for x in clean_manifest["splits"]["test"])
all_p12 = p12_train | p12_val | p12_test

p9_images = set(x["image"] for split in json.load(open(p9_path))["splits"].values() for x in split)
p10_images = set(x["image"] for split in json.load(open(p10_path))["splits"].values() for x in split)
all_historical = p9_images | p10_images | all_p12

# Parse tab
patches = {}
with open(tab_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("/*") or line.startswith("Image set"):
            continue
        parts = line.split("\t")
        if len(parts) >= 16:
            subset = parts[0].strip()
            jpg_file = parts[1].strip()
            xml_file = parts[2].strip()
            tag = parts[3].strip()
            start_time = parts[5].strip()
            end_time = parts[6].strip()
            sentinel_id = parts[7].strip()
            ul_lon = parts[10].strip()
            ul_lat = parts[11].strip()
            ur_lon = parts[12].strip() if len(parts) > 12 else ""
            ur_lat = parts[13].strip() if len(parts) > 13 else ""
            br_lon = parts[14].strip() if len(parts) > 14 else ""
            br_lat = parts[15].strip() if len(parts) > 15 else ""
            
            clean_safes = [s.strip() for s in sentinel_id.split(";") if s.strip()]
            label = 1 if subset in ("ow", "oc") else 0
            class_name = "oil_slick_candidate" if label == 1 else "look_alike"
            
            parts_tag = tag.split("-")
            cluster = "oil"
            if subset in ("nw", "nc") and len(parts_tag) >= 3:
                cluster = f"{parts_tag[0]}_c{parts_tag[2]}"
                
            ul_lo = float(ul_lon) if ul_lon else None
            ul_la = float(ul_lat) if ul_lat else None
            br_lo = float(br_lon) if br_lon else None
            br_la = float(br_lat) if br_lat else None
            
            center_lat = (ul_la + br_la) / 2.0 if (ul_la and br_la) else ul_la
            center_lon = (ul_lo + br_lo) / 2.0 if (ul_lo and br_lo) else ul_lo
            
            if jpg_file not in patches:
                patches[jpg_file] = {
                    "image": jpg_file,
                    "xml": xml_file,
                    "subset": subset,
                    "label": label,
                    "class_name": class_name,
                    "tag": tag,
                    "cluster": cluster,
                    "safes": clean_safes,
                    "raw_scene": sentinel_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "ul_lon": ul_lo,
                    "ul_lat": ul_la,
                    "br_lon": br_lo,
                    "br_lat": br_la,
                    "center_lat": round(center_lat, 6) if center_lat else None,
                    "center_lon": round(center_lon, 6) if center_lon else None,
                    "is_coastal": subset in ("oc", "nc"),
                    "in_historical": jpg_file in all_historical,
                }

# Build connected components
safe_to_patches = defaultdict(set)
patch_to_safes = defaultdict(set)
for img, p in patches.items():
    for s in p["safes"]:
        safe_to_patches[s].add(img)
        patch_to_safes[img].add(s)

patch_adj = defaultdict(set)
for s, img_set in safe_to_patches.items():
    imgs = list(img_set)
    for i in range(len(imgs)):
        for j in range(i + 1, len(imgs)):
            patch_adj[imgs[i]].add(imgs[j])
            patch_adj[imgs[j]].add(imgs[i])

visited = set()
components = []
for img in sorted(patches.keys()):
    if img not in visited:
        comp_patches = []
        queue = [img]
        visited.add(img)
        while queue:
            curr = queue.pop(0)
            comp_patches.append(curr)
            for neighbor in patch_adj[curr]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        comp_safes = set()
        for p_img in comp_patches:
            comp_safes.update(patch_to_safes[p_img])
        components.append({
            "patches": sorted(comp_patches),
            "safes": sorted(list(comp_safes))
        })

print(f"Total components: {len(components)}")

# Separate into historical vs completely unused unseen
unseen_comps = []
for idx, c in enumerate(components):
    p_list = c["patches"]
    has_hist = any(patches[p]["in_historical"] for p in p_list)
    if not has_hist:
        oil_cnt = sum(1 for p in p_list if patches[p]["label"] == 1)
        la_cnt = sum(1 for p in p_list if patches[p]["label"] == 0)
        unseen_comps.append({
            "id": idx,
            "patches": p_list,
            "safes": c["safes"],
            "oil_cnt": oil_cnt,
            "la_cnt": la_cnt,
            "total": len(p_list)
        })

print(f"Remaining unused unseen components: {len(unseen_comps)}")
print(f"Remaining unused patches: {sum(c['total'] for c in unseen_comps)} (Oil: {sum(c['oil_cnt'] for c in unseen_comps)}, LA: {sum(c['la_cnt'] for c in unseen_comps)})")

# Filter pool of components of manageable size (<= 6 patches per component) to form balanced splits
pool = [c for c in unseen_comps if c["total"] <= 6 and c["oil_cnt"] <= 4 and c["la_cnt"] <= 4]
print(f"Pool of compact components: {len(pool)}")

rng = random.Random(20261103)
rng.shuffle(pool)

# 1. Select env_dev: 60 patches (30 oil, 30 look-alike)
dev_comps = []
o, l = 0, 0
used_ids = set()
for c in pool:
    if o + c["oil_cnt"] <= 30 and l + c["la_cnt"] <= 30:
        dev_comps.append(c)
        used_ids.add(c["id"])
        o += c["oil_cnt"]
        l += c["la_cnt"]
    if o == 30 and l == 30:
        break

print(f"env_dev: {len(dev_comps)} comps, oil={o}, la={l}, total={sum(c['total'] for c in dev_comps)}")

# 2. Select env_val: 40 patches (20 oil, 20 look-alike)
val_comps = []
o, l = 0, 0
for c in pool:
    if c["id"] in used_ids:
        continue
    if o + c["oil_cnt"] <= 20 and l + c["la_cnt"] <= 20:
        val_comps.append(c)
        used_ids.add(c["id"])
        o += c["oil_cnt"]
        l += c["la_cnt"]
    if o == 20 and l == 20:
        break

print(f"env_val: {len(val_comps)} comps, oil={o}, la={l}, total={sum(c['total'] for c in val_comps)}")

# 3. Select locked_final_test: 100 patches (50 oil, 50 look-alike)
test_comps = []
o, l = 0, 0
for c in pool:
    if c["id"] in used_ids:
        continue
    if o + c["oil_cnt"] <= 50 and l + c["la_cnt"] <= 50:
        test_comps.append(c)
        used_ids.add(c["id"])
        o += c["oil_cnt"]
        l += c["la_cnt"]
    if o == 50 and l == 50:
        break

print(f"locked_final_test: {len(test_comps)} comps, oil={o}, la={l}, total={sum(c['total'] for c in test_comps)}")

# Assertions
dev_patches = [p for c in dev_comps for p in c["patches"]]
val_patches = [p for c in val_comps for p in c["patches"]]
test_patches = [p for c in test_comps for p in c["patches"]]

dev_safes = set(s for c in dev_comps for s in c["safes"])
val_safes = set(s for c in val_comps for s in c["safes"])
test_safes = set(s for c in test_comps for s in c["safes"])

assert len(set(dev_patches) & set(val_patches)) == 0
assert len(set(dev_patches) & set(test_patches)) == 0
assert len(set(val_patches) & set(test_patches)) == 0

assert len(dev_safes & val_safes) == 0
assert len(dev_safes & test_safes) == 0
assert len(val_safes & test_safes) == 0

# Check overlap with ALL historical
p12_safes = set(s for split in clean_manifest["splits"].values() for item in split for s in item["safes"])
all_new_safes = dev_safes | val_safes | test_safes
assert len(all_new_safes & p12_safes) == 0, f"SAFE overlap with Phase 12! {len(all_new_safes & p12_safes)}"

all_new_patches = set(dev_patches + val_patches + test_patches)
assert len(all_new_patches & all_historical) == 0, "Patch overlap with historical!"

print("ALL ASSERTIONS PASSED! 100% disjoint, 0 patch overlap, 0 SAFE overlap.")

# Assemble manifest
phase13_manifest = {
    "metadata": {
        "dataset_name": "PANGAEA 980773 / DARTIS 2019 (Phase 13 Environmental Context Benchmark)",
        "citation": "Yang & Singha (2025), Earth System Science Data, DOI: 10.5194/essd-17-6807-2025",
        "license": "CC BY 4.0",
        "sensor": "Sentinel-1 C-SAR GRD (VV amplitude)",
        "total_new_samples": len(all_new_patches),
        "split_counts": {
            "env_dev": {"total": len(dev_patches), "oil": sum(1 for p in dev_patches if patches[p]["label"] == 1), "look_alike": sum(1 for p in dev_patches if patches[p]["label"] == 0), "components": len(dev_comps), "unique_safes": len(dev_safes)},
            "env_val": {"total": len(val_patches), "oil": sum(1 for p in val_patches if patches[p]["label"] == 1), "look_alike": sum(1 for p in val_patches if patches[p]["label"] == 0), "components": len(val_comps), "unique_safes": len(val_safes)},
            "locked_final_test": {"total": len(test_patches), "oil": sum(1 for p in test_patches if patches[p]["label"] == 1), "look_alike": sum(1 for p in test_patches if patches[p]["label"] == 0), "components": len(test_comps), "unique_safes": len(test_safes)},
        },
        "audit_guarantees": {
            "patch_overlap_between_splits": 0,
            "safe_overlap_between_splits": 0,
            "component_overlap_between_splits": 0,
            "patch_overlap_with_phase12": 0,
            "safe_overlap_with_phase12": 0,
            "all_components_unseen_in_phase_9_10_11_12": True
        }
    },
    "splits": {
        "env_dev": [patches[p] for p in dev_patches],
        "env_val": [patches[p] for p in val_patches],
        "locked_final_test": [patches[p] for p in test_patches]
    }
}

out_manifest_path = Path("data/training/sar_oil_v2/sar_splits_phase13_manifest.json")
with open(out_manifest_path, "w", encoding="utf-8") as f:
    json.dump(phase13_manifest, f, indent=2)

print(f"Phase 13 manifest successfully saved to {out_manifest_path} ({len(all_new_patches)} patches)")
