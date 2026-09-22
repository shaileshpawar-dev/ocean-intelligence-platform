# Dataset coverage

Generated 2026-09-22T15:54:08+00:00 by `python -m app.water.cli coverage --markdown` from the local database. Every figure is a count over the tables; nothing here is estimated.

## Totals

| Measure | Value |
|---|---|
| States / UTs listed by the source | 35 |
| States / UTs with observations loaded | 35 |
| States / UTs without data | 0 (none) |
| Districts | 506 |
| Cities (curated district groupings) | 35 |
| Water bodies | 2,595 (other 798, groundwater 735, river 403, lake 309, pond 167, reservoir 59, drain 40, coastal 35, canal 31, creek 18) |
| Monitoring stations | 4,000 (4,000 with coordinates) |
| Observations | 582,192 |
| Observation dates | 2018-01-01 to 2025-01-01 |
| Water-body geometries cached | 119 |
| Administrative boundaries | district 735, state 36 |

The latest date differs by state: most state extracts end in 2020 or 2021, and only a few stations have anything newer (see the Latest column). The national upper date must not be read as the date of the data in general. See LIMITATIONS.md.

## By state / UT

| Code | State / UT | Source resources | Districts | Water bodies | Stations | Observations | First | Latest | Note |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| AP | Andhra Pradesh | 6 | 18 | 182 | 220 | 38,425 | 2018-01-03 | 2021-12-27 |  |
| AR | Arunachal Pradesh | 6 | 8 | 13 | 13 | 319 | 2018-01-08 | 2021-12-19 |  |
| AS | Assam | 6 | 22 | 169 | 203 | 34,422 | 2018-01-03 | 2021-12-29 |  |
| BR | Bihar | 6 | 31 | 80 | 167 | 24,213 | 2018-01-04 | 2021-12-30 |  |
| CG | Chhattisgarh | 6 | 9 | 27 | 63 | 8,645 | 2018-01-01 | 2021-12-23 |  |
| CH | Chandigarh | 6 | 1 | 12 | 13 | 1,645 | 2018-01-04 | 2021-12-10 |  |
| DD | Daman and Diu | 6 | 2 | 9 | 13 | 1,650 | 2018-01-07 | 2021-12-29 |  |
| DL | Delhi | 6 | 8 | 54 | 59 | 3,436 | 2018-01-01 | 2021-12-30 |  |
| DN | Dadra and Nagar Haveli | 6 | 2 | 9 | 13 | 1,650 | 2018-01-07 | 2021-12-29 |  |
| GA | Goa | 6 | 2 | 52 | 64 | 12,185 | 2018-01-01 | 2021-12-15 |  |
| GJ | Gujarat | 6 | 23 | 142 | 182 | 26,254 | 2018-01-01 | 2021-12-29 |  |
| HP | Himachal Pradesh | 6 | 10 | 103 | 197 | 28,078 | 2018-01-05 | 2021-12-30 |  |
| HR | Haryana | 6 | 18 | 50 | 88 | 7,720 | 2018-01-01 | 2021-12-29 |  |
| JH | Jharkhand | 6 | 12 | 32 | 72 | 7,801 | 2018-01-09 | 2021-12-30 |  |
| JK | Jammu and Kashmir | 6 | 9 | 46 | 110 | 8,954 | 2018-01-01 | 2021-12-29 |  |
| KA | Karnataka | 6 | 28 | 195 | 274 | 61,370 | 2018-01-03 | 2021-12-31 |  |
| KL | Kerala | 6 | 14 | 113 | 133 | 25,784 | 2018-01-01 | 2021-12-28 |  |
| LD | Lakshadweep | 6 | 1 | 44 | 45 | 1,051 | 2018-01-11 | 2021-11-03 |  |
| MH | Maharashtra | 6 | 31 | 126 | 227 | 25,507 | 2018-01-01 | 2021-12-28 |  |
| ML | Meghalaya | 7 | 9 | 58 | 95 | 17,035 | 2018-01-03 | 2025-01-01 |  |
| MN | Manipur | 6 | 9 | 37 | 67 | 8,676 | 2018-01-02 | 2021-12-31 |  |
| MP | Madhya Pradesh | 6 | 39 | 131 | 243 | 40,119 | 2018-01-01 | 2021-12-31 |  |
| MZ | Mizoram | 6 | 8 | 67 | 76 | 11,302 | 2018-01-08 | 2021-12-19 |  |
| NL | Nagaland | 6 | 6 | 15 | 28 | 4,187 | 2018-01-10 | 2021-12-13 |  |
| OD | Odisha | 6 | 27 | 134 | 245 | 43,341 | 2018-01-01 | 2021-12-16 |  |
| PB | Punjab | 6 | 15 | 52 | 111 | 14,896 | 2018-01-03 | 2021-12-23 |  |
| PY | Puducherry | 6 | 2 | 21 | 22 | 1,521 | 2018-01-03 | 2021-12-21 |  |
| RJ | Rajasthan | 6 | 30 | 149 | 177 | 18,158 | 2018-01-03 | 2021-12-31 |  |
| SK | Sikkim | 6 | 4 | 8 | 12 | 2,351 | 2018-01-03 | 2021-12-23 |  |
| TN | Tamil Nadu | 6 | 22 | 67 | 133 | 18,158 | 2018-01-02 | 2021-12-21 |  |
| TR | Tripura | 6 | 4 | 95 | 119 | 14,643 | 2018-01-11 | 2021-12-16 |  |
| TS | Telangana | 6 | 10 | 100 | 142 | 20,879 | 2018-01-03 | 2021-12-24 |  |
| UK | Uttarakhand | 6 | 8 | 38 | 59 | 5,430 | 2018-01-03 | 2021-12-22 |  |
| UP | Uttar Pradesh | 6 | 45 | 65 | 175 | 23,559 | 2018-01-01 | 2021-12-30 |  |
| WB | West Bengal | 6 | 19 | 100 | 140 | 18,828 | 2018-01-02 | 2021-12-30 |  |
