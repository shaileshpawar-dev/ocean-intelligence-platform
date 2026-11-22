import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PIL import Image

manifest_path = Path("data/training/sar_oil_v2/sar_splits_phase13_manifest.json")
img_dir = Path("data/training/sar_oil_v2/images")
img_dir.mkdir(parents=True, exist_ok=True)

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest = json.load(f)

all_images = []
for split_name, items in manifest["splits"].items():
    for item in items:
        all_images.append(item["image"])

print(f"Total images to ensure in {img_dir}: {len(all_images)}")

base_url = "https://download.pangaea.de/dataset/980773/files/"
session = requests.Session()

def download_image(img_name):
    target = img_dir / img_name
    if target.exists() and target.stat().st_size > 1000:
        try:
            with Image.open(target) as im:
                im.verify()
            return img_name, True, "cached"
        except Exception:
            pass

    url = base_url + img_name
    for attempt in range(4):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(target, "wb") as f:
                    f.write(r.content)
                with Image.open(target) as im:
                    im.verify()
                return img_name, True, "downloaded"
            time.sleep(0.5 * (attempt + 1))
        except Exception as e:
            time.sleep(1.0 * (attempt + 1))
            
    return img_name, False, "failed"

print("Starting concurrent download with 8 workers...")
t0 = time.time()
success = 0
failed = []

with ThreadPoolExecutor(max_workers=8) as executor:
    futures = {executor.submit(download_image, img): img for img in all_images}
    for future in as_completed(futures):
        img_name, ok, status = future.result()
        if ok:
            success += 1
        else:
            failed.append(img_name)
        if success % 25 == 0 or success == len(all_images):
            print(f"Progress: {success}/{len(all_images)} ({time.time() - t0:.1f}s)")

print(f"Download complete in {time.time() - t0:.1f}s: Success={success}, Failed={len(failed)}")
if failed:
    print(f"Failed images: {failed}")
    exit(1)
else:
    print("ALL 200 PHASE 13 IMAGES SUCCESSFULLY DOWNLOADED AND VERIFIED VIA PIL!")
