# The detection pipeline

This document explains what the platform detects, why it is limited to that,
and how the two-stage design follows from the physics rather than from a
preference for complexity.

## 1. What Sentinel-1 measures

Sentinel-1 carries a C-band (5.405 GHz) synthetic aperture radar. It transmits
a microwave pulse and measures the backscattered return. Over water, the
dominant mechanism is **Bragg scattering**: the radar resonates with short
gravity-capillary waves (centimetre scale) on the sea surface.

The measured quantity, VV backscatter in decibels, is therefore a proxy for
**surface roughness at centimetre scale**. It is not a measure of colour,
chemistry, temperature, or composition.

Typical open-ocean VV values at moderate wind sit around −8 to −18 dB.

## 2. What that permits as a claim

A surface film — oil, but also biogenic material — increases surface tension
and damps those short waves. Less Bragg scattering means less return, so the
region appears **dark**. This is a *dark formation*, and detecting it is the
accepted first stage of every operational SAR oil-spill service, including
EMSA's CleanSeaNet.

What a dark formation does **not** tell you:

- **What the substance is.** Crude oil, refined product, biogenic slick from a
  plankton bloom, and a patch of unusually calm water all damp the same waves.
- **How thick it is.** Backscatter saturates; a monomolecular sheen and a
  centimetre of crude can look similar.
- **Anything about material below the surface.** Dissolved chemicals and
  suspended plastics have no C-band surface-roughness signature at all.

### Look-alikes

These produce dark formations and are the reason a dark patch is not evidence
of oil on its own:

| Look-alike | Mechanism |
|---|---|
| Low wind (< ~3 m/s) | Too few capillary waves exist to scatter from |
| Biogenic slicks | Algal exudates damp waves exactly as oil does |
| Rain cells | Attenuation and surface disruption |
| Wind shadows | Sheltering by land or by orographic effects |
| Grease ice | High-latitude surface damping |
| Upwelling / current shear | Local suppression of the wave field |

The platform attaches this caveat to **every** positive detection. It is not
a footnote; it is the honest content of the claim.

## 3. Why the original approach was wrong

The predecessor system computed regional backscatter statistics — which was
sound — and then did this:

```python
raw_cells.sort(key=lambda x: x["mean_vv"])
bucket = min(i // max(1, bucket_size), 4)
types_ordered = ["oil_spill", "marine_debris", "plastic_waste",
                 "algae_bloom", "chemical_pollution"]
type_map[cell["cell_name"]] = types_ordered[bucket]
```

Three independent failures:

1. **Every cell is labelled polluted by construction.** Rank order always
   fills all five buckets. Feed it 37 pristine cells and it still reports
   seven oil spills. There is no detection step, no threshold, no possibility
   of a negative result.
2. **The classes are physically underivable.** Plastic and dissolved chemicals
   have no C-band signature. Algae blooms require optical instruments
   (chlorophyll-a absorption in Sentinel-2 bands). No amount of statistics on
   a VV histogram recovers them.
3. **Confidence was fabricated.** `0.70 + abs(mean_vv + 18) * 0.02` is a
   function of brightness, presented as a model probability.

## 4. What this platform does instead

### Stage 1 — screening

`SARDarkFormationDetector` consumes the per-cell reducer output (mean, p10,
p90, stdDev of VV in dB) and asks two questions:

**Is anything dark?** If the 10th percentile is above the darkness threshold
(default −22 dB), the answer is no, and the detector returns an explicit
`no_anomaly`. A negative is a result: it records that the cell was observed.

**Is the darkness structured?** This is the discriminating question. Contrast
is `p90 − p10`:

- **Low contrast** (< 3 dB) means the cell is *uniformly* dark. A slick is a
  dark patch inside a normally-scattering sea; a low-wind zone is dark
  everywhere. Uniform darkness therefore yields `dark_formation` with a low
  score and a leading caveat naming low wind as the more likely explanation.
- **High contrast** means a dark tail against a normal background — the
  structural signature of a localised film — and permits `oil_like_signature`,
  subject to the plausibility gate below.

The score combines depth below threshold and contrast, each normalised to
[0, 1] and saturating, then mapped into [0.30, 0.85]. **The cap is deliberate**:
a rule-based heuristic must never present as near-certainty, and
`confidence_is_calibrated` is `False` on every output because the score has
never been validated against labelled spills.

Wind, when available, is the strongest disambiguator: below 3 m/s the score is
halved and a caveat says the signature is not separable from the background;
above 10 m/s a persistent dark patch is harder to explain away and the score
is modestly raised.

### The plausibility gate

Extent is estimated by interpolating the implied distribution between the p10
and p90 anchors — deliberately coarse, and labelled as such.

For scale: Deepwater Horizon, among the largest marine spills on record,
peaked in the low thousands of km². The gate is set at **5,000 km²**. A
contiguous dark region beyond that is not a slick; it is a met-ocean feature.
Such detections are **downgraded** from `oil_like_signature` to
`dark_formation`, their confidence scaled by 0.4, and the reason recorded in
`extra.downgrade_reason`.

Downgrading at the detector, rather than at display time, means an
implausible claim never enters the database or a report.

### Why stage 2 exists

Applying that gate to the screening grid produced a striking result: **every**
coarse detection degraded. The reason is arithmetic. Cells are 10⁴–10⁵ km²; an
8°×8° cell is roughly 800,000 km². A dark fraction of even 10% is ~78,000 km²
— fifteen times the gate.

At screening resolution an oil-slick claim is *unsupportable in principle*.

The wrong response is to raise the gate until claims pass. The right response
is to look closer:

```
Stage 1   40 cells · 1 GEE call each · whole Indian EEZ
          → "Gulf of Kutch W shows anomalous dark structure"
          → max claim: dark_formation

Stage 2   subdivide 6×6 → 9,334 km² sub-cells · re-query
          → 3,077 km² localised dark patch
          → oil_like_signature is now supportable
```

`subdivision_factor()` targets a sub-cell area of 2.5× the plausibility gate,
capped at 8× per axis so cost stays bounded (≤64 calls per refined cell), and
only cells already flagged as anomalous are refined.

This is the standard operational pattern — screen wide and cheap, confirm
narrow and expensive — arrived at here by following the constraint rather than
by imitation.

## 5. The signature guardrail

`BaseDetector` declares `supported_signatures`, and `_validate()` raises if a
detector emits anything outside its set:

```python
supported_signatures = frozenset({
    PollutionSignature.OIL_LIKE_SIGNATURE,
    PollutionSignature.DARK_FORMATION,
    PollutionSignature.NO_ANOMALY,
})
```

A SAR detector *cannot* return "plastic waste" — not by convention, but
because the call raises. This is the structural fix for the original bug, and
`TestSignatureGuardrail` runs it in CI.

## 6. The optical path

`YOLODetector` wraps the existing YOLOv8m checkpoint, which was trained on
labelled optical imagery and is the one genuinely learned component inherited
from the original project.

Metadata read directly out of `best.pt`:

| Field | Value |
|---|---|
| Architecture | YOLOv8m (25,858,636 parameters), task `detect` |
| Framework | ultralytics 8.4.41 |
| Trained | 2026-04-22, resumed from `ocean_v3/weights/last.pt` |
| Dataset | `pollution.yaml` |
| Schedule | 100 epochs, 640 px, batch 16, lr0 0.001, patience 20, seed 42 |
| Licence | **AGPL-3.0** (Ultralytics) |

### The class map was wrong

The checkpoint's own `names` are:

```
0 oil_spill   1 algae_bloom   2 plastic_waste   3 chemical_pollution
```

The original notebook declared:

```python
CLASS_NAMES = {0: "oil_spill", 1: "algae_bloom",
               2: "plastic_waste", 3: "marine_debris"}   # class 3 is wrong
```

Class 3 is **`chemical_pollution`**, not `marine_debris`. Every class-3
detection that system produced was reported under a label the model never
emitted. The fix is structural rather than a corrected constant: the detector
now reads `names` from the checkpoint at load time and resolves signatures by
label, so a retrained model with reordered or additional classes needs no code
change. An unrecognised label degrades to `SURFACE_ANOMALY` rather than being
guessed into a specific claim.

### `chemical_pollution` is downgraded on purpose

The model was trained to emit that label, and the label is preserved on
`Detection.class_name`. But optical reflectance cannot identify a chemical
species -- what is observable is surface discolouration -- so the *signature*
is `SURFACE_ANOMALY`, and the detection carries a caveat saying exactly that.
This is the same discipline applied to SAR: keep what the model said, state
only what the modality supports.

Two further corrections:

- **Geolocation.** The original assigned `random.uniform(-30, 30)` latitude to
  every detection, placing them in arbitrary oceans. Detections are now
  geolocated only when the caller supplies the source image's bounds;
  otherwise latitude and longitude stay `None` with a caveat. An absent
  coordinate is more useful than a fabricated one.
- **Optional loading.** A missing checkpoint or absent `ultralytics` degrades
  to the mock detector with a warning; the platform still starts.

## 7. What would improve this

In rough order of value per unit effort:

1. **Wind fields** (ERA5 / ASCAT). The single highest-value addition — it
   removes the dominant look-alike class outright.
2. **Segmentation** on full-resolution scenes, replacing percentile
   interpolation with a measured mask and a real area.
3. **A labelled dataset.** Without one, every confidence here stays
   uncalibrated. Candidate sources: EMSA CleanSeaNet confirmations, NOAA
   incident archives, published SAR oil-spill benchmarks.
4. **Feature-based look-alike discrimination** — geometry, edge gradient,
   contrast statistics — the classic operational stage-two classifier.
5. **Sentinel-2 fusion** for the optical-only signatures.
6. **Ancillary context**: AIS vessel tracks, bathymetry, known platform
   locations.

See [limitations.md](limitations.md) for what remains out of reach and why.
