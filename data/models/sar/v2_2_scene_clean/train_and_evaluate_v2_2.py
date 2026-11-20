import json
import time
import math
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

# Ensure reproducibility
SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)

data_dir = Path("data/training/sar_oil_v2")
images_dir = data_dir / "images"
manifest_path = data_dir / "sar_splits_v2_2_clean_manifest.json"

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest = json.load(f)

print("=" * 80)
print("PHASE 12: SAR MODEL V2.2 TRAINING & EVALUATION PIPELINE")
print("=" * 80)
print(f"Loaded manifest: {manifest_path}")
print(f"Splits: Train={len(manifest['splits']['train'])}, Val={len(manifest['splits']['val'])}, Test={len(manifest['splits']['test'])}")

class CleanSARDataset(Dataset):
    def __init__(self, items, img_dir, is_train=False, img_size=(224, 224)):
        self.items = items
        self.img_dir = img_dir
        self.is_train = is_train
        self.img_size = img_size

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        item = self.items[idx]
        img_path = self.img_dir / item["image"]
        with Image.open(img_path) as im:
            im_gray = im.convert("L").resize(self.img_size, Image.Resampling.BILINEAR)
            
            # Simple data augmentation for training
            if self.is_train:
                if np.random.rand() > 0.5:
                    im_gray = im_gray.transpose(Image.FLIP_LEFT_RIGHT)
                if np.random.rand() > 0.5:
                    im_gray = im_gray.transpose(Image.FLIP_TOP_BOTTOM)
                if np.random.rand() > 0.5:
                    im_gray = im_gray.rotate(90)
                    
            arr = np.array(im_gray, dtype=np.float32) / 255.0
            
        tensor = torch.from_numpy(arr).unsqueeze(0)  # (1, H, W)
        tensor = (tensor - 0.5) / 0.5  # normalize to [-1, 1]
        label = item["label"]
        return tensor, label, item["image"], item["cluster"], item["subset"], item["component_id"]

train_dataset = CleanSARDataset(manifest["splits"]["train"], images_dir, is_train=True)
val_dataset = CleanSARDataset(manifest["splits"]["val"], images_dir, is_train=False)
test_dataset = CleanSARDataset(manifest["splits"]["test"], images_dir, is_train=False)

train_loader = DataLoader(train_dataset, batch_size=16, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=16, shuffle=False)
test_loader = DataLoader(test_dataset, batch_size=1, shuffle=False)

class SAROilSlickMultiScaleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        # Parallel 3x3 and 5x5 branch
        self.conv1_3x3 = nn.Conv2d(1, 12, kernel_size=3, padding=1)
        self.conv1_5x5 = nn.Conv2d(1, 8, kernel_size=5, padding=2)
        self.bn1 = nn.BatchNorm2d(20)
        self.pool1 = nn.MaxPool2d(2, 2)  # 112x112
        
        self.block2 = nn.Sequential(
            nn.Conv2d(20, 40, kernel_size=3, padding=1),
            nn.BatchNorm2d(40),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2)  # 56x56
        )
        self.block3 = nn.Sequential(
            nn.Conv2d(40, 80, kernel_size=3, padding=1),
            nn.BatchNorm2d(80),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2)  # 28x28
        )
        self.block4 = nn.Sequential(
            nn.Conv2d(80, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1))  # 128x1x1
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.4),
            nn.Linear(128, 32),
            nn.ReLU(inplace=True),
            nn.Linear(32, 2)
        )

    def forward(self, x):
        f3 = self.conv1_3x3(x)
        f5 = self.conv1_5x5(x)
        f = self.pool1(F.relu(self.bn1(torch.cat([f3, f5], dim=1))))
        f = self.block2(f)
        f = self.block3(f)
        f = self.block4(f)
        return self.classifier(f)

# Historical baseline model architecture for comparisons
class SAROilSlickCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1))
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.3),
            nn.Linear(128, 32),
            nn.ReLU(inplace=True),
            nn.Linear(32, 2)
        )

    def forward(self, x):
        return self.classifier(self.features(x))

device = torch.device("cpu")
model = SAROilSlickMultiScaleCNN().to(device)
param_count = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(f"Model initialized: SAROilSlickMultiScaleCNN ({param_count:,} parameters) on CPU")

epochs = 25
lr = 1e-3
weight_decay = 1e-4
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

best_val_f1 = 0.0
best_val_acc = 0.0
best_val_metrics = {}
best_weights = None
history = []

print("\n--- Starting Training (25 epochs on CPU) ---")
t_start_train = time.time()

for ep in range(1, epochs + 1):
    t_ep_start = time.time()
    model.train()
    train_loss, train_correct, train_total = 0.0, 0, 0
    for x, y, _, _, _, _ in train_loader:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        out = model(x)
        loss = criterion(out, y)
        loss.backward()
        optimizer.step()
        train_loss += loss.item() * x.size(0)
        preds = torch.argmax(out, dim=1)
        train_correct += (preds == y).sum().item()
        train_total += y.size(0)
        
    scheduler.step()
    train_loss /= train_total
    train_acc = train_correct / train_total
    
    # Validation
    model.eval()
    val_loss, tp, fp, tn, fn = 0.0, 0, 0, 0, 0
    with torch.no_grad():
        for x, y, _, _, _, _ in val_loader:
            x, y = x.to(device), y.to(device)
            out = model(x)
            loss = criterion(out, y)
            val_loss += loss.item() * x.size(0)
            preds = torch.argmax(out, dim=1)
            for p, target in zip(preds, y):
                if p == 1 and target == 1: tp += 1
                elif p == 1 and target == 0: fp += 1
                elif p == 0 and target == 0: tn += 1
                elif p == 0 and target == 1: fn += 1
                
    val_total = tp + fp + tn + fn
    val_loss /= val_total
    val_acc = (tp + tn) / val_total
    val_prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    val_rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    val_f1 = (2 * val_prec * val_rec) / (val_prec + val_rec) if (val_prec + val_rec) > 0 else 0.0
    ep_duration = time.time() - t_ep_start
    
    history.append({
        "epoch": ep,
        "train_loss": round(train_loss, 4),
        "train_acc": round(train_acc, 4),
        "val_loss": round(val_loss, 4),
        "val_acc": round(val_acc, 4),
        "val_f1": round(val_f1, 4),
        "epoch_time_s": round(ep_duration, 1)
    })
    
    print(f"Epoch {ep:2d}/{epochs} ({ep_duration:4.1f}s) | Train Loss: {train_loss:.4f}, Acc: {train_acc:.3f} | Val Loss: {val_loss:.4f}, Acc: {val_acc:.3f}, F1: {val_f1:.4f}")
    
    if val_f1 > best_val_f1 or (val_f1 == best_val_f1 and val_acc > best_val_acc):
        best_val_f1 = val_f1
        best_val_acc = val_acc
        best_val_metrics = {
            "val_accuracy": round(val_acc, 4),
            "val_precision": round(val_prec, 4),
            "val_recall": round(val_rec, 4),
            "val_f1": round(val_f1, 4),
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "epoch": ep
        }
        best_weights = {k: v.cpu().clone() for k, v in model.state_dict().items()}

train_total_time = time.time() - t_start_train
print(f"\nTraining completed in {train_total_time:.1f}s ({train_total_time/60:.2f} min).")
print(f"Peak Validation F1: {best_val_f1:.4f} (Accuracy: {best_val_acc:.4f}) achieved at epoch {best_val_metrics.get('epoch')}")

# Load best checkpoint for validation threshold sweep
model.load_state_dict(best_weights)
model.eval()

# THRESHOLD SWEEP ON VALIDATION DATA ONLY
val_probs = []
val_targets = []
with torch.no_grad():
    for x, y, _, _, _, _ in val_loader:
        out = model(x.to(device))
        probs = torch.softmax(out, dim=1)[:, 1]
        val_probs.extend(probs.cpu().numpy().tolist())
        val_targets.extend(y.cpu().numpy().tolist())

val_probs = np.array(val_probs)
val_targets = np.array(val_targets)

print("\n--- Validation Decision Threshold Sweep (0.35 to 0.70) ---")
threshold_candidates = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
best_thresh = 0.50
best_thresh_f1 = 0.0
thresh_results = []

for th in threshold_candidates:
    preds = (val_probs >= th).astype(int)
    tp = int(np.sum((preds == 1) & (val_targets == 1)))
    fp = int(np.sum((preds == 1) & (val_targets == 0)))
    tn = int(np.sum((preds == 0) & (val_targets == 0)))
    fn = int(np.sum((preds == 0) & (val_targets == 1)))
    acc = (tp + tn) / len(val_targets)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
    
    thresh_results.append({
        "threshold": th,
        "accuracy": round(acc, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn
    })
    print(f"  Thresh={th:.2f} | Acc={acc:.4f}, Prec={prec:.4f}, Rec={rec:.4f}, F1={f1:.4f} | FP={fp:2d}, FN={fn:2d}")
    if f1 > best_thresh_f1:
        best_thresh_f1 = f1
        best_thresh = th

print(f"\nSelected Decision Threshold: {best_thresh:.2f} (based on Peak Val F1 = {best_thresh_f1:.4f})")

# SAVE BEST CHECKPOINT TO data/models/sar/v2_2_scene_clean/best.pt
out_dir = Path("data/models/sar/v2_2_scene_clean")
out_dir.mkdir(parents=True, exist_ok=True)
ckpt_path = out_dir / "best.pt"

checkpoint_payload = {
    "model_name": "sar-oil-slick-v2.2",
    "architecture": "SAROilSlickMultiScaleCNN",
    "param_count": param_count,
    "input_channels": 1,
    "input_resolution": [224, 224],
    "classes": ["look_alike", "oil_slick_candidate"],
    "decision_threshold": best_thresh,
    "training_date": "2026-11-03T13:45:00Z",
    "random_seed": SEED,
    "epochs_trained": epochs,
    "training_samples": len(train_dataset),
    "validation_samples": len(val_dataset),
    "training_history": history,
    "validation_threshold_sweep": thresh_results,
    "state_dict": best_weights
}
torch.save(checkpoint_payload, ckpt_path)
print(f"Saved best checkpoint to {ckpt_path} ({ckpt_path.stat().st_size:,} bytes)")

# EVALUATION OF ALL 4 DETECTORS ON THE EXACT SAME 100 UNSEEN TEST SAMPLES
print("\n" + "=" * 80)
print("EVALUATING ALL 4 DETECTORS ON THE 100 UNSEEN HELD-OUT TEST SAMPLES")
print("=" * 80)

# Load existing checkpoints
# 1. Historical V2 (120-patch)
hist_v2_path = Path("data/models/sar/v2/best.pt")
ckpt_hist_v2 = torch.load(hist_v2_path, map_location="cpu", weights_only=False)
model_hist_v2 = SAROilSlickCNN().to(device)
model_hist_v2.load_state_dict(ckpt_hist_v2["state_dict"])
model_hist_v2.eval()

# 2. Expanded V2.1 (500-patch)
exp_v2_1_path = Path("data/models/sar/v2_expanded/best.pt")
ckpt_exp_v2_1 = torch.load(exp_v2_1_path, map_location="cpu", weights_only=False)
model_exp_v2_1 = SAROilSlickMultiScaleCNN().to(device)
model_exp_v2_1.load_state_dict(ckpt_exp_v2_1["state_dict"])
model_exp_v2_1.eval()

# 3. New V2.2
model_v2_2 = model

# Run inference across test set
targets = []
preds_base = []
preds_v2 = []
preds_v2_1 = []
preds_v2_2 = []

probs_v2 = []
probs_v2_1 = []
probs_v2_2 = []

test_items = manifest["splits"]["test"]
latencies_v2_2_inf = []
latencies_v2_2_prep = []

prediction_records = []

for idx, (x, y, img_name, cluster, subset, comp_id) in enumerate(test_loader):
    img = img_name[0]
    tgt = y.item()
    targets.append(tgt)
    
    # Measure preprocessing separately
    t0_prep = time.perf_counter()
    with Image.open(images_dir / img) as im_raw:
        im_l = im_raw.convert("L")
        arr_raw = np.array(im_l, dtype=np.float32)
        im_resized = im_l.resize((224, 224), Image.Resampling.BILINEAR)
        arr_norm = np.array(im_resized, dtype=np.float32) / 255.0
    t_prep_ms = (time.perf_counter() - t0_prep) * 1000.0
    latencies_v2_2_prep.append(t_prep_ms)
    
    # 1. Baseline Heuristic
    mean_val = float(np.mean(arr_raw))
    p10_val = float(np.percentile(arr_raw, 10))
    contrast = mean_val - p10_val
    b_pred = 1 if (contrast > 25.0 and p10_val < 75.0) else 0
    preds_base.append(b_pred)
    
    # 2. Historical V2
    with torch.no_grad():
        out_v2 = model_hist_v2(x.to(device))
        p_v2 = torch.softmax(out_v2, dim=1)[:, 1].item()
    probs_v2.append(p_v2)
    preds_v2.append(1 if p_v2 >= 0.50 else 0)
    
    # 3. Expanded V2.1
    with torch.no_grad():
        out_v2_1 = model_exp_v2_1(x.to(device))
        p_v2_1 = torch.softmax(out_v2_1, dim=1)[:, 1].item()
    probs_v2_1.append(p_v2_1)
    preds_v2_1.append(1 if p_v2_1 >= 0.50 else 0)
    
    # 4. New V2.2
    t0_inf = time.perf_counter()
    with torch.no_grad():
        out_v2_2 = model_v2_2(x.to(device))
        p_v2_2 = torch.softmax(out_v2_2, dim=1)[:, 1].item()
    t_inf_ms = (time.perf_counter() - t0_inf) * 1000.0
    latencies_v2_2_inf.append(t_inf_ms)
    
    probs_v2_2.append(p_v2_2)
    p_pred = 1 if p_v2_2 >= best_thresh else 0
    preds_v2_2.append(p_pred)
    
    prediction_records.append({
        "image": img,
        "subset": subset[0],
        "cluster": cluster[0],
        "component_id": comp_id.item(),
        "ground_truth": tgt,
        "pred_baseline": b_pred,
        "prob_v2": round(p_v2, 4),
        "pred_v2": preds_v2[-1],
        "prob_v2_1": round(p_v2_1, 4),
        "pred_v2_1": preds_v2_1[-1],
        "prob_v2_2": round(p_v2_2, 4),
        "pred_v2_2": p_pred,
        "v2_2_is_correct": p_pred == tgt
    })

targets = np.array(targets)
preds_base = np.array(preds_base)
preds_v2 = np.array(preds_v2)
preds_v2_1 = np.array(preds_v2_1)
preds_v2_2 = np.array(preds_v2_2)

def compute_full_metrics(preds, tgts):
    tp = int(np.sum((preds == 1) & (tgts == 1)))
    fp = int(np.sum((preds == 1) & (tgts == 0)))
    tn = int(np.sum((preds == 0) & (tgts == 0)))
    fn = int(np.sum((preds == 0) & (tgts == 1)))
    tot = len(tgts)
    acc = (tp + tn) / tot
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
    return {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "Accuracy": round(acc, 4),
        "Precision": round(prec, 4),
        "Recall": round(rec, 4),
        "F1": round(f1, 4),
        "FPR": round(fpr, 4),
        "FNR": round(fnr, 4)
    }

metrics_base = compute_full_metrics(preds_base, targets)
metrics_v2 = compute_full_metrics(preds_v2, targets)
metrics_v2_1 = compute_full_metrics(preds_v2_1, targets)
metrics_v2_2 = compute_full_metrics(preds_v2_2, targets)

# Display Comparison Table
print(f"\n{'Metric':<12} | {'Baseline (v1)':<15} | {'SAR V2 (120)':<15} | {'SAR V2.1 (500)':<15} | {'SAR V2.2 (Clean)':<18}")
print("-" * 85)
for k in ["TP", "FP", "TN", "FN"]:
    print(f"{k:<12} | {metrics_base[k]:<15d} | {metrics_v2[k]:<15d} | {metrics_v2_1[k]:<15d} | {metrics_v2_2[k]:<18d}")
for k in ["Accuracy", "Precision", "Recall", "F1", "FPR", "FNR"]:
    print(f"{k:<12} | {metrics_base[k]:<15.4f} | {metrics_v2[k]:<15.4f} | {metrics_v2_1[k]:<15.4f} | {metrics_v2_2[k]:<18.4f}")

# Latency Benchmark
mean_prep = float(np.mean(latencies_v2_2_prep))
med_prep = float(np.median(latencies_v2_2_prep))
p95_prep = float(np.percentile(latencies_v2_2_prep, 95))

mean_inf = float(np.mean(latencies_v2_2_inf))
med_inf = float(np.median(latencies_v2_2_inf))
p95_inf = float(np.percentile(latencies_v2_2_inf, 95))

total_lat = [p + i for p, i in zip(latencies_v2_2_prep, latencies_v2_2_inf)]
mean_tot = float(np.mean(total_lat))
med_tot = float(np.median(total_lat))
p95_tot = float(np.percentile(total_lat, 95))

print(f"\nMeasured CPU Latency Benchmark (Batch Size 1, {len(test_items)} patches):")
print(f"  Preprocessing: Mean={mean_prep:.2f} ms | Median={med_prep:.2f} ms | P95={p95_prep:.2f} ms")
print(f"  Inference:     Mean={mean_inf:.2f} ms | Median={med_inf:.2f} ms | P95={p95_inf:.2f} ms")
print(f"  Total Latency: Mean={mean_tot:.2f} ms | Median={med_tot:.2f} ms | P95={p95_tot:.2f} ms")

# McNemar Statistical Significance Comparisons
def mcnemar_test(preds_a, preds_b, tgts):
    corr_a = (preds_a == tgts)
    corr_b = (preds_b == tgts)
    b = int(np.sum(corr_a & ~corr_b))
    c = int(np.sum(~corr_a & corr_b))
    n = b + c
    if n == 0:
        return b, c, 1.0
    k = min(b, c)
    p_val = 2.0 * sum(math.comb(n, i) * (0.5 ** n) for i in range(k + 1))
    p_val = min(1.0, p_val)
    return b, c, round(p_val, 4)

b_22_21, c_22_21, p_22_21 = mcnemar_test(preds_v2_2, preds_v2_1, targets)
b_22_v2, c_22_v2, p_22_v2 = mcnemar_test(preds_v2_2, preds_v2, targets)
b_22_base, c_22_base, p_22_base = mcnemar_test(preds_v2_2, preds_base, targets)

print(f"\nMcNemar Significance Tests (Two-Sided Exact Binomial):")
print(f"  V2.2 vs V2.1: V2.2 correct/V2.1 wrong={b_22_21}, V2.2 wrong/V2.1 correct={c_22_21} -> p-value = {p_22_21}")
print(f"  V2.2 vs V2.0: V2.2 correct/V2.0 wrong={b_22_v2}, V2.2 wrong/V2.0 correct={c_22_v2} -> p-value = {p_22_v2}")
print(f"  V2.2 vs Baseline: V2.2 correct/Base wrong={b_22_base}, V2.2 wrong/Base correct={c_22_base} -> p-value = {p_22_base}")

# False Positive and False Negative Error Analysis
false_positives = [r for r in prediction_records if r["pred_v2_2"] == 1 and r["ground_truth"] == 0]
false_negatives = [r for r in prediction_records if r["pred_v2_2"] == 0 and r["ground_truth"] == 1]
true_positives = [r for r in prediction_records if r["pred_v2_2"] == 1 and r["ground_truth"] == 1]
true_negatives = [r for r in prediction_records if r["pred_v2_2"] == 0 and r["ground_truth"] == 0]

fp_by_cluster = Counter(r["cluster"] for r in false_positives)
fn_by_subset = Counter(r["subset"] for r in false_negatives)
tp_by_subset = Counter(r["subset"] for r in true_positives)

print(f"\nV2.2 Error Analysis on 100 Unseen Test Samples:")
print(f"  False Positives ({len(false_positives)} total) by Look-Alike Cluster:")
for c, cnt in fp_by_cluster.most_common():
    print(f"    {c}: {cnt}")

print(f"  False Negatives ({len(false_negatives)} total) by Oil Subset:")
for s, cnt in fn_by_subset.items():
    print(f"    {s}: {cnt}")

# Per-Category Performance
print(f"\nPer-Category Breakdown for SAR V2.2:")
all_clusters = sorted(list(set(r["cluster"] for r in prediction_records)))
for c in all_clusters:
    recs = [r for r in prediction_records if r["cluster"] == c]
    c_tot = len(recs)
    c_corr = sum(1 for r in recs if r["v2_2_is_correct"])
    print(f"  Cluster {c:<10}: {c_corr}/{c_tot} correct ({c_corr/c_tot*100:.1f}%)")

# Save evaluation report JSON
eval_metrics_data = {
    "model_name": "sar-oil-slick-v2.2",
    "architecture": "SAROilSlickMultiScaleCNN",
    "param_count": param_count,
    "decision_threshold": best_thresh,
    "training_samples": len(train_dataset),
    "validation_samples": len(val_dataset),
    "test_samples": len(test_dataset),
    "test_leakage_free": True,
    "test_metrics": metrics_v2_2,
    "baseline_comparison": {
        "baseline_v1": metrics_base,
        "historical_v2_120": metrics_v2,
        "expanded_v2_1_500": metrics_v2_1,
        "new_v2_2_clean": metrics_v2_2
    },
    "mcnemar_tests": {
        "v2_2_vs_v2_1": {"b": b_22_21, "c": c_22_21, "p_value": p_22_21},
        "v2_2_vs_v2_0": {"b": b_22_v2, "c": c_22_v2, "p_value": p_22_v2},
        "v2_2_vs_baseline": {"b": b_22_base, "c": c_22_base, "p_value": p_22_base}
    },
    "latency_benchmark_ms": {
        "preprocessing": {"mean": mean_prep, "median": med_prep, "p95": p95_prep},
        "inference": {"mean": mean_inf, "median": med_inf, "p95": p95_inf},
        "total": {"mean": mean_tot, "median": med_tot, "p95": p95_tot}
    },
    "validation_threshold_sweep": thresh_results,
    "false_positives_by_cluster": dict(fp_by_cluster),
    "false_negatives_by_subset": dict(fn_by_subset)
}

with open(out_dir / "eval_metrics.json", "w", encoding="utf-8") as f:
    json.dump(eval_metrics_data, f, indent=2)

with open(out_dir / "predictions.json", "w", encoding="utf-8") as f:
    json.dump(prediction_records, f, indent=2)

print(f"\nSaved evaluation metrics to {out_dir / 'eval_metrics.json'}")
print(f"Saved prediction records to {out_dir / 'predictions.json'}")
