import json
from pathlib import Path
from collections import defaultdict, Counter
import random

tab_path = Path("data/training/sar_oil_v2/pangaea_980773_annotations.tab")
p9_path = Path("data/training/sar_oil_v2/sar_splits_manifest.json")
p10_path = Path("data/training/sar_oil_v2/sar_splits_expanded_manifest.json")
img_dir = Path("data/training/sar_oil_v2/images")
local_files = set(p.name for p in img_dir.glob("*.jpg"))

with open(p9_path, "r", encoding="utf-8") as f:
    p9 = json.load(f)
p9_images = set(x["image"] for split in p9["splits"].values() for x in split)

with open(p10_path, "r", encoding="utf-8") as f:
    p10 = json.load(f)
p10_images = set(x["image"] for split in p10["splits"].values() for x in split)
prev_used_images = p9_images.union(p10_images)

patches = {}
with open(tab_path, "r", encoding="utf-8") as f:
    headers = None
    for line in f:
        line = line.strip()
        if not line or line.startswith("/*"):
            continue
        if line.startswith("Image set"):
            headers = [h.strip() for h in line.split("\t")]
            continue
        parts = line.split("\t")
        if len(parts) >= 8:
            subset = parts[0].strip()
            jpg_file = parts[1].strip()
            xml_file = parts[2].strip()
            tag = parts[3].strip()
            sentinel_id = parts[7].strip()
            raw_safes = [s.strip() for s in sentinel_id.split(";") if s.strip()]
            clean_safes = [s for s in raw_safes if s]
            label = 1 if subset in ("ow", "oc") else 0
            class_name = "oil_slick_candidate" if label == 1 else "look_alike"
            parts_tag = tag.split("-")
            cluster = "oil"
            if subset in ("nw", "nc") and len(parts_tag) >= 3:
                cluster = f"{parts_tag[0]}_c{parts_tag[2]}"
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
                    "is_local": jpg_file in local_files,
                    "in_prev": jpg_file in prev_used_images
                }

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

dev_comps = []
unseen_comps = []

for idx, c in enumerate(components):
    p_list = c["patches"]
    has_prev = any(p in prev_used_images for p in p_list)
    local_p = [p for p in p_list if patches[p]["is_local"]]
    oil_local = sum(1 for p in local_p if patches[p]["label"] == 1)
    la_local = sum(1 for p in local_p if patches[p]["label"] == 0)
    oil_all = sum(1 for p in p_list if patches[p]["label"] == 1)
    la_all = sum(1 for p in p_list if patches[p]["label"] == 0)
    
    comp_obj = {
        "id": idx,
        "patches_all": p_list,
        "patches_local": local_p,
        "safes": c["safes"],
        "oil_local": oil_local,
        "la_local": la_local,
        "oil_all": oil_all,
        "la_all": la_all,
        "is_unseen": not has_prev,
        "is_fully_local": len(local_p) == len(p_list) and len(local_p) > 0
    }
    if has_prev:
        dev_comps.append(comp_obj)
    else:
        unseen_comps.append(comp_obj)

# 1. Select TEST: 43 unseen components totaling exactly 50 oil and 50 look-alike
pool_unseen = [c for c in unseen_comps if c["oil_all"] <= 10 and c["la_all"] <= 10]
rng_test = random.Random(2026)
test_comps = None
for trial in range(5000):
    rng_test.shuffle(pool_unseen)
    sub = []
    o, l = 0, 0
    for c in pool_unseen:
        if o + c["oil_all"] <= 50 and l + c["la_all"] <= 50:
            sub.append(c)
            o += c["oil_all"]
            l += c["la_all"]
            if o == 50 and l == 50:
                test_comps = sub
                break
    if test_comps:
        break

assert test_comps is not None, "Failed to find test components"
test_comp_ids = set(c["id"] for c in test_comps)
test_patches = [p for c in test_comps for p in c["patches_all"]]
test_safes = set(s for c in test_comps for s in c["safes"])

# 2. Select VALIDATION: 66 fully local dev components totaling exactly 40 oil and 40 look-alike
pool_val = [c for c in dev_comps if c["is_fully_local"]]
rng_val = random.Random(2026)
val_comps = None
for trial in range(5000):
    rng_val.shuffle(pool_val)
    sub = []
    o, l = 0, 0
    for c in pool_val:
        if o + c["oil_local"] <= 40 and l + c["la_local"] <= 40:
            sub.append(c)
            o += c["oil_local"]
            l += c["la_local"]
            if o == 40 and l == 40:
                val_comps = sub
                break
    if val_comps:
        break

assert val_comps is not None, "Failed to find val components"
val_comp_ids = set(c["id"] for c in val_comps)
val_patches = [p for c in val_comps for p in c["patches_local"]]
val_safes = set(s for c in val_comps for s in c["safes"])

# 3. Select TRAINING: Remaining dev components!
train_comps = [c for c in dev_comps if c["id"] not in val_comp_ids]
train_comp_ids = set(c["id"] for c in train_comps)
train_patches = [p for c in train_comps for p in c["patches_local"]]
train_safes = set(s for c in train_comps for s in c["safes"])

# Check counts
print("=" * 80)
print("VERIFICATION OF PARTITION COUNTS AND PROPERTIES")
print("=" * 80)
print(f"TRAIN: {len(train_patches)} patches ({sum(1 for p in train_patches if patches[p]['label']==1)} oil, {sum(1 for p in train_patches if patches[p]['label']==0)} la)")
print(f"       {len(train_comps)} components, {len(train_safes)} unique SAFEs")
print(f"VAL  : {len(val_patches)} patches ({sum(1 for p in val_patches if patches[p]['label']==1)} oil, {sum(1 for p in val_patches if patches[p]['label']==0)} la)")
print(f"       {len(val_comps)} components, {len(val_safes)} unique SAFEs")
print(f"TEST : {len(test_patches)} patches ({sum(1 for p in test_patches if patches[p]['label']==1)} oil, {sum(1 for p in test_patches if patches[p]['label']==0)} la)")
print(f"       {len(test_comps)} components, {len(test_safes)} unique SAFEs")

# Automated Assertions
print("\nRUNNING AUTOMATED STRICT INTEGRITY ASSERTIONS:")
# 1. No patch overlap
train_p_set = set(train_patches)
val_p_set = set(val_patches)
test_p_set = set(test_patches)
assert len(train_p_set.intersection(val_p_set)) == 0, "Train and Val share patches!"
assert len(train_p_set.intersection(test_p_set)) == 0, "Train and Test share patches!"
assert len(val_p_set.intersection(test_p_set)) == 0, "Val and Test share patches!"
print("  [PASS] Zero patch overlap across all 3 partitions.")

# 2. No component overlap
assert len(train_comp_ids.intersection(val_comp_ids)) == 0, "Train and Val share components!"
assert len(train_comp_ids.intersection(test_comp_ids)) == 0, "Train and Test share components!"
assert len(val_comp_ids.intersection(test_comp_ids)) == 0, "Val and Test share components!"
print("  [PASS] Zero connected component overlap across all 3 partitions.")

# 3. No SAFE identifier overlap
assert len(train_safes.intersection(val_safes)) == 0, f"Train and Val share SAFEs: {train_safes.intersection(val_safes)}"
assert len(train_safes.intersection(test_safes)) == 0, f"Train and Test share SAFEs: {train_safes.intersection(test_safes)}"
assert len(val_safes.intersection(test_safes)) == 0, f"Val and Test share SAFEs: {val_safes.intersection(test_safes)}"
print("  [PASS] Zero SAFE acquisition identifier overlap across all 3 partitions.")

# 4. Genuinely unseen test set
overlap_with_prev = test_p_set.intersection(prev_used_images)
assert len(overlap_with_prev) == 0, f"Test shares patches with Phase 9/10: {overlap_with_prev}"
test_safes_in_dev = test_safes.intersection(train_safes.union(val_safes))
assert len(test_safes_in_dev) == 0, f"Test shares SAFEs with dev: {test_safes_in_dev}"
print("  [PASS] 100% of Final Test components and patches are genuinely unseen and independent.")

print("\nALL AUTOMATED INTEGRITY ASSERTIONS PASSED WITH ZERO VIOLATIONS!")
