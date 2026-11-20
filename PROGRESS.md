# Progress log

Work towards the demo, following `docs/SECTION_AUDIT.md`. Newest entry last.

Database backup taken before any of this work: `backups/oip-20261120-115423.dump`
(113 MB, custom format, 41 tables with data). Restore with:

```bash
docker exec -i ocean-intelligence-platform-db-1 pg_restore -U oip -d oip --clean < backups/oip-20261120-115423.dump
```

---

## Task 1 — Fix the two stale wind-screener tests

**Done.** `tests/test_wind_screener.py::TestMultiSensorIntegrator` — both tests
now call `integrate()` the way `tests/test_multi_sensor_fusion.py` and
`app/services/candidate_service.py:796` call it. No production code changed.

Three things had drifted, not one:

1. `integrate()` takes the candidate's own fields as keywords
   (`sar_confidence`, `screening_status`, `model_version`, `sar_time`,
   `wind_speed_ms`) instead of a packed `sar_result` dict.
2. `optical_evidence` takes real Sentinel-2 band metrics (`mean_ndci`,
   `p90_ndci`, `mean_swir_ratio`, cloud/water fractions) instead of
   pre-interpreted booleans (`ndci_algae_detected`, `sunglint_slick_detected`).
3. Two result fields were renamed: `optical_cross_verification_status` →
   `optical_verification_status`, and `overall_confidence_level` →
   `concordance_level` (now a `ConcordanceLevel` enum, not a string).

The assertions keep their original intent — chlorophyll contradicts the oil
reading, glint supports it — because both status strings
(`biogenic_lookalike_confirmed`, `multi_sensor_slick_concordance`) still exist
in `app/vision/multi_sensor.py`. I also added an evidence-consistency assertion
to the sunglint test so both cases check the same two things.

**Tests:** `645 passed, 21 skipped, 0 failed` (was 643 passed / 2 failed).

**Gotcha:** the NDCI threshold that decides biogenic-vs-oil is
`MultiSensorIntegrator.ALGAL_BLOOM_NDCI_THRESHOLD`. The test uses
`mean_ndci=0.15 / p90_ndci=0.23` to sit clearly above it. If that constant is
ever retuned, these tests are the ones that will tell you.

**Next:** Task 2 — register the three evaluated SAR models in `model_versions`.
