# Engine vs LHSAA Validation Report

Generated: 2026-05-23T14:07:45

Compares engine-computed power ratings against LHSAA's published
end-of-season Power Ratings (where available). Engine ratings are
the final-week snapshot from the weekly backfill.

## Summary

| Sport | Season | Engine N | LHSAA N | Matched | Spearman ρ | Pearson r |
|---|---|---|---|---|---|---|
| Football | 2021 | 288 | 0 | 0 | — | — |
| Football | 2022 | 293 | 289 | 288 | 0.9773 | 0.9750 |
| Football | 2023 | 295 | 294 | 294 | 0.9870 | 0.9845 |
| Football | 2024 | 298 | 0 | 0 | — | — |
| Football | 2025 | 298 | 298 | 298 | 0.9892 | 0.9894 |
| Volleyball | 2021 | 199 | 75 | 75 | 0.6529 | 0.6499 |
| Volleyball | 2022 | 209 | 72 | 72 | 0.7012 | 0.7212 |
| Volleyball | 2023 | 211 | 42 | 42 | 0.8293 | 0.8587 |
| Volleyball | 2024 | 220 | 0 | 0 | — | — |
| Volleyball | 2025 | 222 | 0 | 0 | — | — |
| Boys Basketball | 2021 | 287 | 13 | 13 | 0.9286 | 0.9320 |
| Boys Basketball | 2022 | 293 | 94 | 94 | 0.5259 | 0.5239 |
| Boys Basketball | 2023 | 296 | 0 | 0 | — | — |
| Boys Basketball | 2024 | 297 | 131 | 131 | 0.9404 | 0.9423 |
| Boys Basketball | 2025 | 298 | 0 | 0 | — | — |
| Girls Basketball | 2021 | 269 | 0 | 0 | — | — |
| Girls Basketball | 2022 | 277 | 121 | 117 | 0.7345 | 0.7675 |
| Girls Basketball | 2023 | 280 | 118 | 116 | 0.5725 | 0.6073 |
| Girls Basketball | 2024 | 282 | 0 | 0 | — | — |
| Girls Basketball | 2025 | 285 | 0 | 0 | — | — |
| Baseball | 2021 | 265 | 129 | 129 | 0.4119 | 0.4337 |
| Baseball | 2022 | 270 | 206 | 206 | 0.3348 | 0.3743 |
| Baseball | 2023 | 271 | 252 | 247 | 0.5798 | 0.6183 |
| Baseball | 2024 | 271 | 0 | 0 | — | — |
| Baseball | 2025 | 272 | 0 | 0 | — | — |
| Softball | 2021 | 241 | 38 | 38 | 0.9045 | 0.9177 |
| Softball | 2022 | 253 | 39 | 39 | 0.7267 | 0.7043 |
| Softball | 2023 | 256 | 0 | 0 | — | — |
| Softball | 2024 | 259 | 229 | 221 | 0.5732 | 0.5639 |
| Softball | 2025 | 263 | 0 | 0 | — | — |
| Boys Soccer | 2021 | 140 | 0 | 0 | — | — |
| Boys Soccer | 2022 | 147 | 0 | 0 | — | — |
| Boys Soccer | 2023 | 149 | 0 | 0 | — | — |
| Boys Soccer | 2024 | 150 | 0 | 0 | — | — |
| Boys Soccer | 2025 | 155 | 0 | 0 | — | — |
| Girls Soccer | 2021 | 134 | 0 | 0 | — | — |
| Girls Soccer | 2022 | 138 | 0 | 0 | — | — |
| Girls Soccer | 2023 | 138 | 0 | 0 | — | — |
| Girls Soccer | 2024 | 139 | 0 | 0 | — | — |
| Girls Soccer | 2025 | 142 | 0 | 0 | — | — |

## Football 2021 <a id="football-2021"></a>

- Engine teams: **288** (max week 10)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/football_2021_weekly.csv`](data/validation/football_2021_weekly.csv)

## Football 2022 <a id="football-2022"></a>

- Engine teams: **293** (max week 10)
- LHSAA teams: **289**
- Matched (overlap): **288**
- Spearman ρ overall: **0.9773**
- Pearson r overall : **0.9750**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 55 | 0.9863 | 0.9820 |
| II | 70 | 0.9838 | 0.9835 |
| III | 70 | 0.9657 | 0.9617 |
| IV | 46 | 0.9480 | 0.9597 |
| V | 47 | 0.9787 | 0.9856 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Northside | III | 36 | 57 | -21 |
| Patrick Taylor - Science/Tech. | III | 52 | 41 | +11 |
| A.J. Ellender | II | 33 | 43 | -10 |
| St. Amant | II | 40 | 30 | +10 |
| East Jefferson | II | 50 | 40 | +10 |
| Sacred Heart | III | 22 | 12 | +10 |
| Magnolia School of Excellence | III | 63 | 53 | +10 |
| South Plaquemines | IV | 10 | 20 | -10 |
| Rayville | IV | 42 | 32 | +10 |
| Capitol | IV | 46 | 36 | +10 |

📊 Weekly trajectories: [`data/validation/football_2022_weekly.csv`](data/validation/football_2022_weekly.csv)

## Football 2023 <a id="football-2023"></a>

- Engine teams: **295** (max week 10)
- LHSAA teams: **294**
- Matched (overlap): **294**
- Spearman ρ overall: **0.9870**
- Pearson r overall : **0.9845**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 65 | 0.9809 | 0.9888 |
| II | 64 | 0.9878 | 0.9897 |
| III | 37 | 0.9533 | 0.9636 |
| IV | 68 | 0.9818 | 0.9812 |
| V | 60 | 0.9930 | 0.9925 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Franklin | I | 46 | 25 | +21 |
| South Plaquemines | IV | 8 | 27 | -19 |
| Crowley | III | 21 | 33 | -12 |
| Chalmette | II | 25 | 14 | +11 |
| Ascension Episcopal | II | 23 | 33 | -10 |
| Bonnabel | I | 37 | 47 | -10 |
| DeQuincy | IV | 53 | 62 | -9 |
| Oakdale | IV | 32 | 24 | +8 |
| McDonogh #35 | II | 34 | 26 | +8 |
| Belle Chasse | IV | 18 | 25 | -7 |

📊 Weekly trajectories: [`data/validation/football_2023_weekly.csv`](data/validation/football_2023_weekly.csv)

## Football 2024 <a id="football-2024"></a>

- Engine teams: **298** (max week 10)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/football_2024_weekly.csv`](data/validation/football_2024_weekly.csv)

## Football 2025 <a id="football-2025"></a>

- Engine teams: **298** (max week 10)
- LHSAA teams: **298**
- Matched (overlap): **298**
- Spearman ρ overall: **0.9892**
- Pearson r overall : **0.9894**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 77 | 0.9922 | 0.9931 |
| II | 74 | 0.9888 | 0.9935 |
| III | 75 | 0.9818 | 0.9906 |
| IV | 72 | 0.9836 | 0.9838 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Tioga | I | 24 | 9 | +15 |
| De La Salle | III | 23 | 38 | -15 |
| Pearl River | II | 41 | 27 | +14 |
| Grand Lake | IV | 43 | 31 | +12 |
| Parkview Baptist | III | 24 | 35 | -11 |
| Pope John Paul II | III | 28 | 39 | -11 |
| Rayne | II | 38 | 48 | -10 |
| Crescent City | IV | 54 | 64 | -10 |
| St. Augustine | I | 12 | 3 | +9 |
| Lafayette | I | 58 | 49 | +9 |

📊 Weekly trajectories: [`data/validation/football_2025_weekly.csv`](data/validation/football_2025_weekly.csv)

## Volleyball 2021 <a id="volleyball-2021"></a>

- Engine teams: **199** (max week 8)
- LHSAA teams: **75**
- Matched (overlap): **75**
- Spearman ρ overall: **0.6529**
- Pearson r overall : **0.6499**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 14 | 0.7349 | 0.6915 |
| II | 16 | 0.8676 | 0.8345 |
| III | 18 | 0.5723 | 0.6165 |
| IV | 13 | 0.7637 | 0.8295 |
| V | 14 | 0.5604 | 0.7020 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Edna Karr | II | 30 | 15 | +15 |
| Covenant Christian | V | 21 | 7 | +14 |
| Zachary | I | 22 | 10 | +12 |
| Centerville | V | 23 | 11 | +12 |
| St. Louis Catholic | III | 6 | 18 | -12 |
| Ascension Christian | V | 15 | 5 | +10 |
| West Ouachita | II | 20 | 10 | +10 |
| Church Point | III | 8 | 17 | -9 |
| West Feliciana | III | 21 | 12 | +9 |
| Southern Lab | V | 18 | 10 | +8 |

📊 Weekly trajectories: [`data/validation/volleyball_2021_weekly.csv`](data/validation/volleyball_2021_weekly.csv)

## Volleyball 2022 <a id="volleyball-2022"></a>

- Engine teams: **209** (max week 9)
- LHSAA teams: **72**
- Matched (overlap): **72**
- Spearman ρ overall: **0.7012**
- Pearson r overall : **0.7212**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 12 | 0.5604 | 0.8513 |
| II | 16 | 0.9235 | 0.8643 |
| III | 13 | 0.9066 | 0.9024 |
| IV | 17 | 0.8064 | 0.9031 |
| V | 14 | 0.8286 | 0.9524 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Riverdale | I | 27 | 12 | +15 |
| A.J. Ellender | II | 31 | 16 | +15 |
| St. Thomas Aquinas | IV | 19 | 11 | +8 |
| Hahnville | I | 10 | 2 | +8 |
| Northlake Christian | V | 14 | 6 | +8 |
| Many | IV | 11 | 17 | -6 |
| South Lafourche | II | 20 | 14 | +6 |
| John Curtis Christian | IV | 9 | 4 | +5 |
| South Plaquemines | IV | 10 | 15 | -5 |
| St. Charles | IV | 15 | 10 | +5 |

📊 Weekly trajectories: [`data/validation/volleyball_2022_weekly.csv`](data/validation/volleyball_2022_weekly.csv)

## Volleyball 2023 <a id="volleyball-2023"></a>

- Engine teams: **211** (max week 9)
- LHSAA teams: **42**
- Matched (overlap): **42**
- Spearman ρ overall: **0.8293**
- Pearson r overall : **0.8587**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 11 | 0.8368 | 0.9329 |
| II | 3 | 0.5000 | 0.6692 |
| III | 13 | 0.8846 | 0.9199 |
| IV | 15 | 0.8786 | 0.9220 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Loyola Prep | IV | 28 | 14 | +14 |
| St. Charles | IV | 21 | 13 | +8 |
| Lutcher | III | 16 | 9 | +7 |
| De La Salle | III | 20 | 13 | +7 |
| John Curtis Christian | IV | 9 | 2 | +7 |
| Terrebonne | I | 15 | 9 | +6 |
| Morgan City | II | 8 | 3 | +5 |
| St. Thomas Aquinas | IV | 16 | 11 | +5 |
| Archbishop Shaw | I | 3 | 7 | -4 |
| Calvary Baptist | IV | 2 | 6 | -4 |

📊 Weekly trajectories: [`data/validation/volleyball_2023_weekly.csv`](data/validation/volleyball_2023_weekly.csv)

## Volleyball 2024 <a id="volleyball-2024"></a>

- Engine teams: **220** (max week 9)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/volleyball_2024_weekly.csv`](data/validation/volleyball_2024_weekly.csv)

## Volleyball 2025 <a id="volleyball-2025"></a>

- Engine teams: **222** (max week 9)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/volleyball_2025_weekly.csv`](data/validation/volleyball_2025_weekly.csv)

## Boys Basketball 2021 <a id="boys-basketball-2021"></a>

- Engine teams: **287** (max week 14)
- LHSAA teams: **13**
- Matched (overlap): **13**
- Spearman ρ overall: **0.9286**
- Pearson r overall : **0.9320**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| II | 1 | — | — |
| IV | 11 | 0.9545 | 0.9404 |
| V | 1 | — | — |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| St. Charles | II | 47 | 1 | +46 |
| Pope John Paul II | IV | 51 | 10 | +41 |
| Houma Christian | IV | 48 | 11 | +37 |
| Northlake Christian | IV | 42 | 7 | +35 |
| Ascension Episcopal | V | 26 | 1 | +25 |
| Catholic - N.I. | IV | 33 | 9 | +24 |
| St. Thomas Aquinas | IV | 27 | 8 | +19 |
| Lafayette Christian | IV | 15 | 6 | +9 |
| Holy Savior Menard | IV | 12 | 4 | +8 |
| Episcopal | IV | 11 | 5 | +6 |

📊 Weekly trajectories: [`data/validation/boys_basketball_2021_weekly.csv`](data/validation/boys_basketball_2021_weekly.csv)

## Boys Basketball 2022 <a id="boys-basketball-2022"></a>

- Engine teams: **293** (max week 13)
- LHSAA teams: **94**
- Matched (overlap): **94**
- Spearman ρ overall: **0.5259**
- Pearson r overall : **0.5239**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 21 | 0.4077 | 0.4017 |
| II | 19 | 0.4193 | 0.3185 |
| III | 16 | 0.3676 | 0.3996 |
| IV | 18 | 0.8741 | 0.8926 |
| V | 20 | 0.5273 | 0.5003 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Holy Cross | I | 53 | 10 | +43 |
| Archbishop Rummel | I | 54 | 12 | +42 |
| Crescent City | V | 43 | 2 | +41 |
| Bunkie | III | 47 | 8 | +39 |
| Vandebilt Catholic | II | 43 | 5 | +38 |
| Warren Easton | I | 55 | 17 | +38 |
| John Ehret | I | 48 | 11 | +37 |
| Pineville | I | 37 | 5 | +32 |
| St. Augustine | I | 39 | 7 | +32 |
| Lafayette | I | 52 | 20 | +32 |

📊 Weekly trajectories: [`data/validation/boys_basketball_2022_weekly.csv`](data/validation/boys_basketball_2022_weekly.csv)

## Boys Basketball 2023 <a id="boys-basketball-2023"></a>

- Engine teams: **296** (max week 14)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/boys_basketball_2023_weekly.csv`](data/validation/boys_basketball_2023_weekly.csv)

## Boys Basketball 2024 <a id="boys-basketball-2024"></a>

- Engine teams: **297** (max week 13)
- LHSAA teams: **131**
- Matched (overlap): **131**
- Spearman ρ overall: **0.9404**
- Pearson r overall : **0.9423**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 28 | 0.9865 | 0.9942 |
| II | 28 | 0.9464 | 0.9621 |
| III | 22 | 0.9252 | 0.9193 |
| IV | 25 | 0.9054 | 0.9382 |
| V | 28 | 0.9780 | 0.9874 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| East Jefferson | I | 62 | 25 | +37 |
| West Jefferson | I | 64 | 27 | +37 |
| C.E. Byrd | I | 60 | 24 | +36 |
| Kenner Discovery Health Science | II | 63 | 27 | +36 |
| Acadiana | I | 57 | 22 | +35 |
| Riverdale | I | 61 | 26 | +35 |
| L. W. Higgins | I | 63 | 28 | +35 |
| John Ehret | I | 56 | 23 | +33 |
| Livingston Collegiate | III | 53 | 21 | +32 |
| Northlake Christian | IV | 44 | 12 | +32 |

📊 Weekly trajectories: [`data/validation/boys_basketball_2024_weekly.csv`](data/validation/boys_basketball_2024_weekly.csv)

## Boys Basketball 2025 <a id="boys-basketball-2025"></a>

- Engine teams: **298** (max week 14)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/boys_basketball_2025_weekly.csv`](data/validation/boys_basketball_2025_weekly.csv)

## Girls Basketball 2021 <a id="girls-basketball-2021"></a>

- Engine teams: **269** (max week 13)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/girls_basketball_2021_weekly.csv`](data/validation/girls_basketball_2021_weekly.csv)

## Girls Basketball 2022 <a id="girls-basketball-2022"></a>

- Engine teams: **277** (max week 13)
- LHSAA teams: **121**
- Matched (overlap): **117**
- Spearman ρ overall: **0.7345**
- Pearson r overall : **0.7675**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 25 | 0.7692 | 0.7820 |
| II | 28 | 0.5977 | 0.7379 |
| III | 16 | 0.5206 | 0.6593 |
| IV | 21 | 0.7065 | 0.7787 |
| V | 27 | 0.9296 | 0.9269 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Tioga | II | 56 | 9 | +47 |
| Riverdale | I | 57 | 12 | +45 |
| Bonnabel | I | 60 | 17 | +43 |
| Abramson | II | 60 | 17 | +43 |
| Slaughter Community Charter | IV | 52 | 11 | +41 |
| Frederick A Douglass | II | 52 | 13 | +39 |
| Buckeye | III | 44 | 5 | +39 |
| L. W. Higgins | I | 54 | 16 | +38 |
| Pineville | I | 59 | 21 | +38 |
| Northlake Christian | IV | 48 | 10 | +38 |

📊 Weekly trajectories: [`data/validation/girls_basketball_2022_weekly.csv`](data/validation/girls_basketball_2022_weekly.csv)

## Girls Basketball 2023 <a id="girls-basketball-2023"></a>

- Engine teams: **280** (max week 13)
- LHSAA teams: **118**
- Matched (overlap): **116**
- Spearman ρ overall: **0.5725**
- Pearson r overall : **0.6073**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 24 | 0.5252 | 0.5554 |
| II | 26 | 0.5133 | 0.5071 |
| III | 18 | 0.4118 | 0.3979 |
| IV | 21 | 0.8247 | 0.8394 |
| V | 27 | 0.6331 | 0.6314 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| McKinley | II | 59 | 16 | +43 |
| John Ehret | I | 59 | 17 | +42 |
| East Jefferson | I | 60 | 18 | +42 |
| L. W. Higgins | I | 50 | 12 | +38 |
| Sarah T. Reed | IV | 51 | 13 | +38 |
| Riverdale | I | 45 | 8 | +37 |
| Edna Karr | I | 46 | 9 | +37 |
| Lake Charles College Prep | III | 43 | 7 | +36 |
| Thrive Academy | I | 57 | 22 | +35 |
| Evangel Christian | I | 61 | 26 | +35 |

📊 Weekly trajectories: [`data/validation/girls_basketball_2023_weekly.csv`](data/validation/girls_basketball_2023_weekly.csv)

## Girls Basketball 2024 <a id="girls-basketball-2024"></a>

- Engine teams: **282** (max week 14)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/girls_basketball_2024_weekly.csv`](data/validation/girls_basketball_2024_weekly.csv)

## Girls Basketball 2025 <a id="girls-basketball-2025"></a>

- Engine teams: **285** (max week 13)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/girls_basketball_2025_weekly.csv`](data/validation/girls_basketball_2025_weekly.csv)

## Baseball 2021 <a id="baseball-2021"></a>

- Engine teams: **265** (max week 9)
- LHSAA teams: **129**
- Matched (overlap): **129**
- Spearman ρ overall: **0.4119**
- Pearson r overall : **0.4337**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 31 | 0.5408 | 0.7026 |
| II | 32 | 0.2841 | 0.2661 |
| III | 24 | 0.4431 | 0.4726 |
| IV | 24 | 0.4684 | 0.4035 |
| V | 18 | 0.5005 | 0.4566 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Iowa | II | 48 | 7 | +41 |
| Barbe | I | 41 | 1 | +40 |
| Edna Karr | I | 63 | 28 | +35 |
| Neville | I | 52 | 18 | +34 |
| Airline | I | 65 | 31 | +34 |
| Centerville | V | 36 | 2 | +34 |
| Thibodaux | I | 57 | 24 | +33 |
| Loreauville | IV | 36 | 3 | +33 |
| Donaldsonville | III | 41 | 8 | +33 |
| Warren Easton | I | 61 | 29 | +32 |

📊 Weekly trajectories: [`data/validation/baseball_2021_weekly.csv`](data/validation/baseball_2021_weekly.csv)

## Baseball 2022 <a id="baseball-2022"></a>

- Engine teams: **270** (max week 9)
- LHSAA teams: **206**
- Matched (overlap): **206**
- Spearman ρ overall: **0.3348**
- Pearson r overall : **0.3743**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 46 | 0.3479 | 0.3602 |
| II | 42 | 0.5380 | 0.6226 |
| III | 36 | 0.5404 | 0.4677 |
| IV | 38 | 0.4778 | 0.4869 |
| V | 44 | 0.5607 | 0.6168 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Sulphur | I | 45 | 4 | +41 |
| Acadiana | I | 52 | 15 | +37 |
| Franklin | I | 10 | 46 | -36 |
| Sam Houston | I | 41 | 6 | +35 |
| C.E. Byrd | I | 4 | 37 | -33 |
| Arcadia | V | 8 | 40 | -32 |
| Archbishop Hannan | II | 9 | 40 | -31 |
| Catholic - B.R. | I | 2 | 33 | -31 |
| Benton | I | 49 | 19 | +30 |
| Teurlings Catholic | II | 37 | 8 | +29 |

📊 Weekly trajectories: [`data/validation/baseball_2022_weekly.csv`](data/validation/baseball_2022_weekly.csv)

## Baseball 2023 <a id="baseball-2023"></a>

- Engine teams: **271** (max week 9)
- LHSAA teams: **252**
- Matched (overlap): **247**
- Spearman ρ overall: **0.5798**
- Pearson r overall : **0.6183**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 60 | 0.4611 | 0.4514 |
| II | 55 | 0.6676 | 0.7382 |
| III | 44 | 0.6632 | 0.6892 |
| IV | 42 | 0.5565 | 0.6404 |
| V | 46 | 0.7980 | 0.7559 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Neville | I | 54 | 8 | +46 |
| Franklin | I | 12 | 57 | -45 |
| St. Thomas More | II | 51 | 6 | +45 |
| Natchitoches Central | I | 47 | 9 | +38 |
| Hahnville | I | 56 | 18 | +38 |
| Southside | I | 46 | 10 | +36 |
| Huntington | I | 26 | 61 | -35 |
| Barbe | I | 37 | 2 | +35 |
| Benton | I | 53 | 20 | +33 |
| Airline | I | 65 | 32 | +33 |

📊 Weekly trajectories: [`data/validation/baseball_2023_weekly.csv`](data/validation/baseball_2023_weekly.csv)

## Baseball 2024 <a id="baseball-2024"></a>

- Engine teams: **271** (max week 9)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/baseball_2024_weekly.csv`](data/validation/baseball_2024_weekly.csv)

## Baseball 2025 <a id="baseball-2025"></a>

- Engine teams: **272** (max week 10)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/baseball_2025_weekly.csv`](data/validation/baseball_2025_weekly.csv)

## Softball 2021 <a id="softball-2021"></a>

- Engine teams: **241** (max week 9)
- LHSAA teams: **38**
- Matched (overlap): **38**
- Spearman ρ overall: **0.9045**
- Pearson r overall : **0.9177**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 4 | 0.8000 | 0.8734 |
| II | 27 | 0.9284 | 0.9404 |
| III | 7 | 0.8571 | 0.9674 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Huntington | I | 38 | 2 | +36 |
| Franklin | I | 39 | 4 | +35 |
| St. Louis Catholic | III | 36 | 7 | +29 |
| Edna Karr | I | 29 | 3 | +26 |
| Neville | I | 20 | 1 | +19 |
| Leesville | II | 35 | 17 | +18 |
| DeRidder | II | 33 | 18 | +15 |
| University Lab | III | 21 | 6 | +15 |
| Rayne | II | 36 | 23 | +13 |
| Thibodaux | II | 26 | 14 | +12 |

📊 Weekly trajectories: [`data/validation/softball_2021_weekly.csv`](data/validation/softball_2021_weekly.csv)

## Softball 2022 <a id="softball-2022"></a>

- Engine teams: **253** (max week 8)
- LHSAA teams: **39**
- Matched (overlap): **39**
- Spearman ρ overall: **0.7267**
- Pearson r overall : **0.7043**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 1 | — | — |
| II | 9 | 0.7833 | 0.7596 |
| III | 7 | 0.6786 | 0.6456 |
| IV | 12 | 0.6333 | 0.5157 |
| V | 10 | 0.9273 | 0.9470 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Peabody | II | 53 | 8 | +45 |
| Evangel Christian | I | 43 | 1 | +42 |
| St. Louis Catholic | III | 44 | 5 | +39 |
| Madison Prep | III | 40 | 6 | +34 |
| Frederick A Douglass | II | 39 | 9 | +30 |
| Thibodaux | II | 32 | 3 | +29 |
| West St. John | V | 37 | 8 | +29 |
| Lake Arthur | IV | 40 | 11 | +29 |
| Teurlings Catholic | II | 33 | 6 | +27 |
| Mangham | IV | 37 | 10 | +27 |

📊 Weekly trajectories: [`data/validation/softball_2022_weekly.csv`](data/validation/softball_2022_weekly.csv)

## Softball 2023 <a id="softball-2023"></a>

- Engine teams: **256** (max week 9)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/softball_2023_weekly.csv`](data/validation/softball_2023_weekly.csv)

## Softball 2024 <a id="softball-2024"></a>

- Engine teams: **259** (max week 9)
- LHSAA teams: **229**
- Matched (overlap): **221**
- Spearman ρ overall: **0.5732**
- Pearson r overall : **0.5639**

**Per-division correlation:**

| Division | N | Spearman ρ | Pearson r |
|---|---|---|---|
| I | 50 | 0.1793 | 0.3351 |
| II | 50 | 0.5332 | 0.5333 |
| III | 40 | 0.3038 | 0.2582 |
| IV | 39 | 0.6452 | 0.6365 |
| V | 42 | 0.9209 | 0.8549 |

**Top 10 rank disagreements (engine − LHSAA):**

| School | Division | Engine rank | LHSAA rank | Δ |
|---|---|---|---|---|
| Evangel Christian | I | 49 | 8 | +41 |
| Sam Houston | I | 9 | 44 | -35 |
| Kaplan | III | 2 | 36 | -34 |
| St. Amant | I | 5 | 38 | -33 |
| Mandeville | I | 13 | 46 | -33 |
| Eunice | II | 16 | 49 | -33 |
| Natchitoches Central | I | 11 | 43 | -32 |
| Caldwell Parish | III | 6 | 38 | -32 |
| Central - B.R. | I | 14 | 45 | -31 |
| Acadiana | I | 39 | 9 | +30 |

📊 Weekly trajectories: [`data/validation/softball_2024_weekly.csv`](data/validation/softball_2024_weekly.csv)

## Softball 2025 <a id="softball-2025"></a>

- Engine teams: **263** (max week 9)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/softball_2025_weekly.csv`](data/validation/softball_2025_weekly.csv)

## Boys Soccer 2021 <a id="boys-soccer-2021"></a>

- Engine teams: **140** (max week 12)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/boys_soccer_2021_weekly.csv`](data/validation/boys_soccer_2021_weekly.csv)

## Boys Soccer 2022 <a id="boys-soccer-2022"></a>

- Engine teams: **147** (max week 11)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/boys_soccer_2022_weekly.csv`](data/validation/boys_soccer_2022_weekly.csv)

## Boys Soccer 2023 <a id="boys-soccer-2023"></a>

- Engine teams: **149** (max week 12)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/boys_soccer_2023_weekly.csv`](data/validation/boys_soccer_2023_weekly.csv)

## Boys Soccer 2024 <a id="boys-soccer-2024"></a>

- Engine teams: **150** (max week 12)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/boys_soccer_2024_weekly.csv`](data/validation/boys_soccer_2024_weekly.csv)

## Boys Soccer 2025 <a id="boys-soccer-2025"></a>

- Engine teams: **155** (max week 12)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/boys_soccer_2025_weekly.csv`](data/validation/boys_soccer_2025_weekly.csv)

## Girls Soccer 2021 <a id="girls-soccer-2021"></a>

- Engine teams: **134** (max week 12)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/girls_soccer_2021_weekly.csv`](data/validation/girls_soccer_2021_weekly.csv)

## Girls Soccer 2022 <a id="girls-soccer-2022"></a>

- Engine teams: **138** (max week 11)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/girls_soccer_2022_weekly.csv`](data/validation/girls_soccer_2022_weekly.csv)

## Girls Soccer 2023 <a id="girls-soccer-2023"></a>

- Engine teams: **138** (max week 12)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/girls_soccer_2023_weekly.csv`](data/validation/girls_soccer_2023_weekly.csv)

## Girls Soccer 2024 <a id="girls-soccer-2024"></a>

- Engine teams: **139** (max week 12)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/girls_soccer_2024_weekly.csv`](data/validation/girls_soccer_2024_weekly.csv)

## Girls Soccer 2025 <a id="girls-soccer-2025"></a>

- Engine teams: **142** (max week 12)
- LHSAA teams: **0**
- Matched (overlap): **0**
- Spearman ρ overall: **—**
- Pearson r overall : **—**

📊 Weekly trajectories: [`data/validation/girls_soccer_2025_weekly.csv`](data/validation/girls_soccer_2025_weekly.csv)
