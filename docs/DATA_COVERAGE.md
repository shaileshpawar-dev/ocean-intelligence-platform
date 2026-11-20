# Data Coverage & Provenance Report

This document reports the exact verified data coverage in the OceanAI PostgreSQL/PostGIS database. Every number is an exact count verified against database tables on 2026-10-16. No number is estimated or fabricated.

---

## 1. Verified Record Counts

| Category | Database Table | Exact Count | Description |
|---|---|---|---|
| **Water Quality Observations** | `water_quality_observations` | **4,601,153** | Physical, chemical, and biological measurements from CWC and CPCB. |
| **Monitoring Stations** | `monitoring_stations` | **4,951** | Physical sampling stations (4,911 manual NWDP + 40 real-time RTWQMS). All have valid latitude/longitude coordinates. |
| **Water Bodies** | `water_bodies` | **2,740** | Harmonised river stretches, lakes, ponds, reservoirs, creeks, and coastal waters. |
| **Water Body Geometries** | `water_body_geometries` | **405** | PostGIS LineString, MultiLineString, and Polygon geometry features matched to water bodies. |
| **Administrative Boundaries** | `states`, `districts` | **771** | Official state/UT (36) and district (735) spatial polygon boundaries. |
| **Curated Cities** | `cities` | **35** | Curated urban agglomerations mapped to constituent district sets (e.g. Mumbai = Mumbai City + Mumbai Suburban). |
| **Satellite Imagery Evidence** | `water_images` | **17** | Copernicus Sentinel-2 L2A bottom-of-atmosphere scenes with optical turbidity/chlorophyll proxies. |
| **Source Classifications** | `source_classifications` | **351** | Official CPCB priority pollution stretch classifications (Priority I to V). |
| **Reference Standards** | `reference_standards` | **6** | Published national water quality standards (e.g. CPCB Bathing Water Criteria, BIS 10500 Drinking Water). |
| **Reference Thresholds** | `reference_thresholds` | **23** | Specific numeric parameter bounds (BOD, DO, pH, Fecal Coliform, Total Coliform). |
| **Research Documents** | `research_documents` | **22** | Official environmental publications and CPCB methodology documents. |
| **RAG Research Chunks** | `research_chunks` | **31** | Text chunks indexed for grounded passage retrieval. |

---

## 2. Ingestion Source Breakdown

| Source Key | Source Name & Agency | Observation Count | Earliest Date | Latest Date | Cadence | Description |
|---|---|---:|---|---|---|---|
| `cwc_nwdp` | CWC Surface Water Quality (Manual) | 4,017,920 | 1963-08-01 | 2025-06-05 | Monthly grab | Long-term historical river and reservoir sampling across major Indian river basins. |
| `cpcb_nwdp` | CPCB Surface Water Quality (Manual) | 582,192 | 2018-01-01 | 2025-01-01 | Monthly grab | National Water Quality Monitoring Programme (NWMP) state pollution board samples. |
| `cpcb_rtwqms` | CPCB Real-Time Monitoring | 1,041 | 2026-09-02 | 2026-09-26 | Hourly sensor | Automated continuous water quality monitoring stations across 6 key states. |
| **Total** | | **4,601,153** | **1963-08-01** | **2026-09-26** | | Deduplicated multi-source observations. |

---

## 3. Top Parameters by Observation Count

| Parameter Key | Parameter Label | Observations | Unit | Standard Limit Applied | Direction |
|---|---|---:|---|---|---|
| `ph` | Potential of Hydrogen (pH) | 307,308 | pH units | 6.5 – 8.5 (Bathing/Drinking) | Two-sided range |
| `electrical_conductivity` | Electrical Conductivity | 276,675 | µS/cm | ≤ 2,250 µS/cm (Irrigation) | Lower is better |
| `dissolved_oxygen` | Dissolved Oxygen (DO) | 245,712 | mg/L | ≥ 5.0 mg/L (Bathing Class B) | Higher is better |
| `temperature` | Water Temperature | 214,323 | °C | Ambient baseline | Informational |
| `chloride` | Chloride | 204,013 | mg/L | ≤ 250 mg/L (Drinking) | Lower is better |
| `bod` | Biochemical Oxygen Demand | 201,221 | mg/L | ≤ 3.0 mg/L (Bathing Class B) | Lower is better |
| `bicarbonate` | Bicarbonate | 200,292 | mg/L | - | Informational |
| `carbonate` | Carbonate | 198,091 | mg/L | - | Informational |
| `calcium` | Calcium | 198,075 | mg/L | ≤ 75 mg/L (Drinking) | Lower is better |
| `magnesium` | Magnesium | 197,986 | mg/L | ≤ 30 mg/L (Drinking) | Lower is better |
| `odour` | Odour | 192,077 | qualitative | Unobjectionable | Qualitative |
| `colour` | Colour | 190,988 | Hazen units | ≤ 10 Hazen (Bathing) | Lower is better |
| `sodium` | Sodium | 179,413 | mg/L | - | Informational |
| `sulphate` | Sulphate | 178,202 | mg/L | ≤ 200 mg/L (Drinking) | Lower is better |
| `total_hardness` | Total Hardness (as CaCO3) | 155,370 | mg/L | ≤ 300 mg/L (Drinking) | Lower is better |

---

## 4. Water Body Classification Breakdown

| Water Body Type | Count | Representative Examples |
|---|---:|---|
| **River** | 581 | Ganga, Yamuna, Mithi, Godavari, Krishna, Narmada, Tapi, Cauvery |
| **Lake** | 315 | Hussain Sagar, Mansar Lake, Sukhna Lake, Lower Lake, Ambazari Lake |
| **Pond / Tank** | 166 | Herohalli Tank, Yelahanka Tank, temple ponds |
| **Reservoir / Dam** | 67 | Dharoi Dam, Chapoli Dam, Nagarjuna Sagar, Bhakra Dam |
| **Drain / Nallah** | 38 | Najafgarh Drain, Bandra Drain, city outfalls |
| **Coastal / Sea Water** | 35 | Juhu Beach, Marine Drive, Marina Beach |
| **Canal** | 31 | Indira Gandhi Canal, Buckingham Canal |
| **Creek** | 18 | Thane Creek, Mahim Creek, Vasai Creek |
| **Groundwater / Wells** | 745 | Open wells, tube wells, borewells |
| **Other / Unclassified** | 744 | Local wetland stretches, unclassified rural stations |
| **Total** | **2,740** | |

---

## 5. Verified Satellite Scenes (Sentinel-2 L2A)

The database links 17 high-resolution Sentinel-2 MSI bottom-of-atmosphere scenes to water bodies, providing optical proxy evidence for turbidity and chlorophyll:

1. **Dharoi Dam** (`dharoi-dam`): Sentinel-2 MSI (2026-09-25)
2. **Sukhna Lake** (`sukhna-lake`): Sentinel-2 MSI (2026-09-20)
3. **Umiam Lake** (`umiam-lake`): Sentinel-2 MSI (2026-03-01)
4. **Loktak Lake** (`loktak-lake`): Sentinel-2 MSI (2026-03-08)
5. **Ambazari Lake** (`ambazari-lake`): Sentinel-2 MSI (2026-09-19)
6. **Himayat Sagar Lake** (`himayat-sagar-lake`): Sentinel-2 MSI (2026-09-06)
7. **Hussain Sagar Lake** (`hussain-sagar-lake`): Sentinel-2 MSI (2026-06-16)
8. **Ramappa Lake** (`ramappa-lake`): Sentinel-2 MSI (2026-09-19)
9. **Herohalli Tank** (`herohalli-tank`): Sentinel-2 MSI (2026-04-29)
10. **Yelahanka Tank** (`yelahanka-tank`): Sentinel-2 MSI (2026-05-12)
11. **Govindgarh Lake** (`govindgarh-lake`): Sentinel-2 MSI (2026-06-16)
12. **Veeranam Lake** (`veeranam-lake`): Sentinel-2 MSI (2026-08-27)
13. **Mansar Lake** (`mansar-lake`): Sentinel-2 MSI (2026-09-23)
14. **Lower Lake** (`lower-lake`): Sentinel-2 MSI (2026-06-09)
15. **Rachenahalli Lake** (`rachenahalli-lake`): Sentinel-2 MSI (2026-04-29)
16. **Chapoli Dam** (`chapoli-dam`): Sentinel-2 MSI (2026-09-15)
17. **Dimna Lake** (`dimna-lake`): Sentinel-2 MSI (2026-06-25)

---

## 6. Freshness & Epistemic Guardrails
- **Freshness Gate**: Any observation older than the declared source reporting horizon (e.g. 90 days for manual NWDP grab samples) is categorized as `NO_RECENT_DATA` for present-tense assessments.
- **Missing vs. Zero**: Missing observations are explicitly stored as `NULL` and displayed as `"not measured"`. They never default to `0.0`.
- **Deduplication**: Ingestion runs are idempotent via unique constraints on `(station_id, parameter, observed_at, source_id)`.
