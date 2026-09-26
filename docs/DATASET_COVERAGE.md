# Dataset coverage

Generated 2026-09-26T03:31:29+00:00 by `python -m app.water.cli coverage --markdown` from the local database. Every figure is a count over the tables; nothing here is estimated.

## Totals

| Measure | Value |
|---|---|
| States / UTs listed by the source | 35 |
| States / UTs with observations loaded | 35 |
| States / UTs without data | 0 (none) |
| Districts | 613 |
| Cities (curated district groupings) | 35 |
| Water bodies | 2,731 (other 745, groundwater 735, river 581, lake 315, pond 166, reservoir 67, drain 38, coastal 35, canal 31, creek 18) |
| Monitoring stations | 4,911 (4,911 with coordinates) |
| Observations | 4,600,112 |
| Observation dates | 1963-08-01 to 2025-06-05 |
| Water-body geometries cached | 405 |
| Administrative boundaries | state 36, district 735 |

The latest date differs by state: most state extracts end in 2020 or 2021, and only a few stations have anything newer (see the Latest column). The national upper date must not be read as the date of the data in general. See LIMITATIONS.md.

## By state / UT

| Code | State / UT | Source resources | Districts | Water bodies | Stations | Observations | First | Latest | Note |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| AP | Andhra Pradesh | 6 | 19 | 186 | 243 | 162,388 | 1972-01-01 | 2025-04-21 |  |
| AR | Arunachal Pradesh | 6 | 16 | 20 | 44 | 115,782 | 2004-01-15 | 2025-06-05 |  |
| AS | Assam | 6 | 28 | 192 | 314 | 445,048 | 1986-06-01 | 2025-06-05 |  |
| BR | Bihar | 6 | 35 | 86 | 198 | 190,393 | 1976-01-01 | 2025-05-22 |  |
| CG | Chhattisgarh | 6 | 18 | 29 | 95 | 187,073 | 1980-06-02 | 2024-09-02 |  |
| CH | Chandigarh | 6 | 1 | 12 | 13 | 1,645 | 2018-01-04 | 2021-12-10 |  |
| DD | Daman and Diu | 6 | 2 | 9 | 13 | 1,650 | 2018-01-07 | 2021-12-29 |  |
| DL | Delhi | 6 | 8 | 58 | 65 | 26,335 | 2007-06-11 | 2025-01-21 |  |
| DN | Dadra and Nagar Haveli | 6 | 2 | 9 | 13 | 1,650 | 2018-01-07 | 2021-12-29 |  |
| GA | Goa | 6 | 2 | 52 | 64 | 12,185 | 2018-01-01 | 2021-12-15 |  |
| GJ | Gujarat | 6 | 23 | 149 | 200 | 91,927 | 1979-06-01 | 2025-03-21 |  |
| HP | Himachal Pradesh | 6 | 10 | 101 | 203 | 49,052 | 2000-07-02 | 2025-05-21 |  |
| HR | Haryana | 6 | 18 | 49 | 91 | 16,648 | 2008-03-04 | 2024-11-21 |  |
| JH | Jharkhand | 6 | 17 | 39 | 96 | 91,541 | 1987-06-01 | 2025-05-21 |  |
| JK | Jammu and Kashmir | 6 | 16 | 48 | 129 | 78,755 | 2004-06-03 | 2025-03-29 |  |
| KA | Karnataka | 6 | 32 | 205 | 319 | 297,651 | 1972-01-01 | 2025-03-21 |  |
| KL | Kerala | 6 | 14 | 123 | 159 | 132,081 | 1980-06-01 | 2025-03-21 |  |
| LD | Lakshadweep | 6 | 1 | 44 | 45 | 1,051 | 2018-01-11 | 2021-11-03 |  |
| MH | Maharashtra | 6 | 33 | 138 | 294 | 324,360 | 1972-09-01 | 2025-04-25 |  |
| ML | Meghalaya | 7 | 9 | 60 | 109 | 36,830 | 2003-06-16 | 2025-03-03 |  |
| MN | Manipur | 6 | 9 | 37 | 68 | 9,552 | 2018-01-02 | 2025-03-03 |  |
| MP | Madhya Pradesh | 6 | 47 | 139 | 309 | 357,868 | 1972-01-01 | 2025-04-21 |  |
| MZ | Mizoram | 6 | 9 | 70 | 83 | 13,103 | 2003-10-01 | 2024-06-21 |  |
| NL | Nagaland | 6 | 6 | 15 | 28 | 4,187 | 2018-01-10 | 2021-12-13 |  |
| OD | Odisha | 6 | 29 | 139 | 296 | 254,543 | 1980-06-01 | 2025-05-23 |  |
| PB | Punjab | 6 | 16 | 55 | 115 | 24,530 | 2018-01-03 | 2023-09-20 |  |
| PY | Puducherry | 6 | 2 | 22 | 25 | 6,216 | 2005-09-01 | 2025-01-21 |  |
| RJ | Rajasthan | 6 | 30 | 150 | 197 | 77,143 | 1976-12-01 | 2025-03-21 |  |
| SK | Sikkim | 6 | 6 | 8 | 48 | 35,478 | 2018-01-03 | 2025-06-02 |  |
| TN | Tamil Nadu | 6 | 33 | 86 | 177 | 215,989 | 1978-06-01 | 2025-04-01 |  |
| TR | Tripura | 6 | 8 | 95 | 132 | 19,906 | 2003-08-01 | 2024-11-21 |  |
| TS | Telangana | 6 | 15 | 105 | 158 | 135,266 | 1972-01-01 | 2025-04-21 |  |
| UK | Uttarakhand | 6 | 11 | 38 | 96 | 144,185 | 1971-10-21 | 2025-04-21 |  |
| UP | Uttar Pradesh | 6 | 66 | 61 | 283 | 855,857 | 1963-08-01 | 2025-04-23 |  |
| WB | West Bengal | 6 | 22 | 102 | 189 | 182,244 | 1986-06-01 | 2025-05-21 |  |
