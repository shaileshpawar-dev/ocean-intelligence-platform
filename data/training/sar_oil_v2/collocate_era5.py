import json
import math
import time
from pathlib import Path
from collections import defaultdict
import requests

from app.vision.era5_client import (
    ERA5Record,
    haversine_distance_km,
    calculate_wind_speed,
    calculate_meteorological_wind_direction,
    LocalERA5Cache,
)

tab_path = Path("data/training/sar_oil_v2/pangaea_980773_annotations.tab")
cache_path = Path("data/cache/era5_wind_cache.json")
p12_manifest_path = Path("data/training/sar_oil_v2/sar_splits_v2_2_clean_manifest.json")
p13_manifest_path = Path("data/training/sar_oil_v2/sar_splits_phase13_manifest.json")

# Load tab metadata
patch_meta = {}
with open(tab_path, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("/*") or line.startswith("Image set"):
            continue
        parts = line.split("\t")
        if len(parts) >= 16:
            img = parts[1].strip()
            if img not in patch_meta:
                subset = parts[0].strip()
                start_time = parts[5].strip()
                end_time = parts[6].strip()
                ul_lon = float(parts[10]) if parts[10] else None
                ul_lat = float(parts[11]) if parts[11] else None
                br_lon = float(parts[14]) if parts[14] else None
                br_lat = float(parts[15]) if parts[15] else None
                c_lat = (ul_lat + br_lat) / 2.0 if (ul_lat and br_lat) else ul_lat
                c_lon = (ul_lon + br_lon) / 2.0 if (ul_lon and br_lon) else ul_lon
                patch_meta[img] = {
                    "image": img,
                    "subset": subset,
                    "start_time": start_time,
                    "end_time": end_time,
                    "center_lat": round(c_lat, 6),
                    "center_lon": round(c_lon, 6),
                    "is_coastal": subset in ("oc", "nc"),
                }

# Identify target patches
with open(p12_manifest_path, "r", encoding="utf-8") as f:
    p12_test = json.load(f)["splits"]["test"]

with open(p13_manifest_path, "r", encoding="utf-8") as f:
    p13 = json.load(f)["splits"]
    p13_all = p13["env_dev"] + p13["env_val"] + p13["locked_final_test"]

target_patches = [x["image"] for x in p12_test] + [x["image"] for x in p13_all]
# ensure uniqueness
target_patches = list(dict.fromkeys(target_patches))
print(f"Total target patches to collocate with ERA5: {len(target_patches)}")

cache = LocalERA5Cache(cache_path)
print(f"Already cached in {cache_path}: {len(cache)}")

to_fetch = [p for p in target_patches if cache.get(p) is None]
print(f"Patches needing ERA5 fetch: {len(to_fetch)}")

# Group by date
date_groups = defaultdict(list)
for p in to_fetch:
    info = patch_meta[p]
    dt_str = info["start_time"][:10]
    date_groups[dt_str].append(info)

print(f"Unique dates to query: {len(date_groups)}")

session = requests.Session()
BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

t0 = time.time()
processed = 0

for dt_str, items in date_groups.items():
    # Batch query up to 10 points
    chunk_size = 10
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        lat_str = ",".join(str(c["center_lat"]) for c in chunk)
        lon_str = ",".join(str(c["center_lon"]) for c in chunk)
        
        params = {
            "latitude": lat_str,
            "longitude": lon_str,
            "start_date": dt_str,
            "end_date": dt_str,
            "hourly": ["wind_speed_10m", "wind_direction_10m", "wind_u_component_10m", "wind_v_component_10m"],
            "wind_speed_unit": "ms",
            "models": "era5",
        }
        
        success = False
        for attempt in range(4):
            try:
                resp = session.get(BASE_URL, params=params, timeout=20)
                if resp.status_code == 200:
                    raw = resp.json()
                    results = raw if isinstance(raw, list) else [raw]
                    for info, res in zip(chunk, results):
                        hourly = res.get("hourly", {})
                        times = hourly.get("time", [])
                        u10_vals = hourly.get("wind_u_component_10m", [])
                        v10_vals = hourly.get("wind_v_component_10m", [])
                        
                        grid_lat = res.get("latitude", round(info["center_lat"] * 4) / 4)
                        grid_lon = res.get("longitude", round(info["center_lon"] * 4) / 4)
                        dist_km = round(haversine_distance_km(info["center_lat"], info["center_lon"], grid_lat, grid_lon), 2)
                        
                        # Parse hour
                        ts = info["start_time"].rstrip("Z")
                        hour = int(ts[11:13])
                        minute = int(ts[14:16])
                        second = int(ts[17:19]) if len(ts) >= 19 else 0
                        minute_frac = minute + second / 60.0
                        
                        alpha = minute_frac / 60.0
                        h0 = hour
                        h1 = min(hour + 1, 23)
                        
                        u0 = u10_vals[h0]
                        v0 = v10_vals[h0]
                        if h1 < len(u10_vals) and h1 != h0:
                            u1 = u10_vals[h1]
                            v1 = v10_vals[h1]
                            u_interp = u0 + alpha * (u1 - u0)
                            v_interp = v0 + alpha * (v1 - v0)
                        else:
                            u_interp = u0
                            v_interp = v0
                            
                        if alpha >= 0.5 and h1 < len(times):
                            sampled_time = times[h1]
                            offset_min = round((1.0 - alpha) * 60.0, 1)
                        else:
                            sampled_time = times[h0]
                            offset_min = round(alpha * 60.0, 1)
                            
                        w_spd = calculate_wind_speed(u_interp, v_interp)
                        w_dir = calculate_meteorological_wind_direction(u_interp, v_interp)
                        
                        rec = ERA5Record(
                            source="ECMWF ERA5 Reanalysis Archive",
                            dataset_version="reanalysis-era5-single-levels",
                            grid_latitude=float(grid_lat),
                            grid_longitude=float(grid_lon),
                            acquisition_timestamp_utc=info["start_time"] + "Z",
                            sampled_timestamp_utc=sampled_time + ":00Z",
                            u10_ms=round(float(u_interp), 2),
                            v10_ms=round(float(v_interp), 2),
                            wind_speed_ms=w_spd,
                            wind_direction_deg=w_dir,
                            temporal_offset_minutes=offset_min,
                            grid_distance_km=dist_km,
                            is_coastal=info["is_coastal"],
                            sampling_method="nearest_grid_linear_time_interp",
                            quality_status="measured_reanalysis",
                        )
                        cache.set(info["image"], rec.to_dict())
                    success = True
                    break
                else:
                    time.sleep(1.0 * (attempt + 1))
            except Exception as e:
                time.sleep(1.0 * (attempt + 1))
        
        if not success:
            print(f"Failed to fetch ERA5 for chunk on {dt_str}")
        processed += len(chunk)
        if processed % 30 == 0 or processed == len(to_fetch):
            print(f"Collocated {processed}/{len(to_fetch)} patches ({time.time() - t0:.1f}s)")
            cache.save()

cache.save()
print(f"All {len(target_patches)} target patches now collocated and cached in {cache_path}!")
