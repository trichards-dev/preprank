# Data Sources

> Established 2026-05-25 as part of v2 TASK 2 Phase 0 cleanup. Reese's spec required documenting source-of-truth decisions after the phantom Div V trace surfaced a fleet-wide ingest bug.

## `teams.division` and `teams.select_status`

**Authoritative source:** LHSAA Power Rating PDFs via `scripts/refresh_team_divisions.py`.

The script reads every PDF in `scripts/lhsaa_pdf_index.json`, parses each with `scripts/parse_lhsaa_pdf.py`, fuzzy-matches each PDF row to an existing team via `(school_id, sport_id, season_year)`, and UPDATEs `teams.division` + `teams.select_status` with the values printed in the PDF. NULL is the only fallback — divisions are **never** inferred from `schools.classification`.

### How to add new years / sports

1. Add the PDF URL(s) to `scripts/lhsaa_pdf_index.json` with the correct `sport`, `season_year`, `division`, `select_status`, and `snapshot` metadata.
2. Run `python -m scripts.refresh_team_divisions` (live) — the script writes the new divisions and logs coverage in `reports/refresh_team_divisions_log.json`.
3. Verify coverage with `python -m scripts.audit run --sports <sport> --seasons <year>`.

### Deprecated approach

The `CLASS_TO_DIV` mapping in `scripts/ingest_football_historical.py` and `scripts/ingest_sports_historical.py` is **deprecated and removed from the write path** (as of 2026-05-25). It is retained only in `scripts/ingest_sports_historical.py:extract_division()` for use by legacy callers parsing district strings; do not introduce new uses. The root cause for retiring it:

- LHSAA Football collapsed Div V → Div IV in the 2022 restructure (now I–IV only for 2022+).
- `CLASS_TO_DIV` was hard-coded with `1A → V`, producing a phantom Div V across 2022–2024 in our `teams.division` data.
- Compounded by `away_class = row["class_"]` (copying reporter's class to opponent regardless of opponent's actual class).
- See `claude-memory/apps/preprank/decisions.md` 2026-05-25 entry "v2 TASK 2 Phase 0 audit shipped" for the full trace.

### Coverage gaps

Coverage is uneven. As of 2026-05-25, 23 of 40 sport-season combos have no PDF in the index — those teams have NULL division. The gaps:

| Sport | Missing seasons |
|---|---|
| Football | 2021, 2024 |
| Volleyball | 2024, 2025 |
| Boys Basketball | 2023, 2025 |
| Girls Basketball | 2021, 2024, 2025 |
| Baseball | 2024, 2025 |
| Softball | 2023, 2025 |
| Boys Soccer | 2021–2025 (all — needs Firecrawl) |
| Girls Soccer | 2021–2025 (all — needs Firecrawl) |

To close the soccer gap, set `FIRECRAWL_API_KEY` in `apps/api/.env` and re-run the refresh. To close the others, source additional PDFs from `lhsaa.org` and add to the index.

### Parser limitation (worth fixing)

`scripts/parse_lhsaa_pdf.py` currently extracts only the first division section from multi-division PDFs (e.g., 2021 Football Select Division Seeding Reports get parsed as 71 Div I rows instead of being split across Div I-V). Most existing Football PDFs in the index were authored using a page-per-division layout that the parser handles correctly; older PDFs with all divisions on one page are mis-parsed. Improving the section-header detection would unlock additional 2021 + sport-specific historical coverage.

## `teams.school_id`, `teams.sport_id`, `teams.season_year`

**Source:** game-scraping scripts (`scripts/ingest_football_historical.py`, `scripts/ingest_sports_historical.py`).

These create the team rows during the lhsaaonline.org schedule scrape. Each (school, sport, season) gets at most one row. As of 2026-05-25, the scripts pass `division=None, select_status=None` to `get_or_create_team` — those fields are owned by the refresh script above.

## `games`

**Source:** `scripts/ingest_football_historical.py` (football) and `scripts/ingest_sports_historical.py` (other 7 sports) scraping `lhsaaonline.org` schedule pages.

Game scores parsed via `parse_scores()`. The `score_format` field on `SportConfig` controls the parsing semantics:

- `"perspective"` (default): the schedule row's `"X-Y"` score means `(my_team, opponent_team)` regardless of W/L.
- `"winner_first"` (Baseball only as of 2026-05-25): the schedule row's `"X-Y"` score means `(winner, loser)` regardless of perspective. Set after Phase 0 audit traced an 87.6% baseball home-win artifact to a score-format mismatch.

If you add a new sport, audit its home-win rate after first ingest. If `> 0.65`, suspect `score_format = "winner_first"`.

## `power_ratings`

**Engine ratings (`source='engine'`):** computed by `scripts/backfill_weekly_engine_ratings.py` from the current `games` + `teams.division` state. Re-run after any change to either table.

**LHSAA-official ratings (`source='lhsaa_official'`):** loaded from PDFs via `scripts/load_lhsaa_official.py`. Same PDF index as `refresh_team_divisions.py`.

## `schools.classification`

**Source:** initial seed (`supabase/seed/seed.py`) from `data/seed/2025_football_power_ratings_final.csv` + supplemental enrichment via `scripts/enrich_schools_maxpreps.py` (currently stashed).

`classification` is the school's **enrollment-based class** (5A, 4A, 3A, 2A, 1A, B, C). It is a per-school, lifetime-stable field that **does NOT change per-season**. Do not use it to infer per-season playoff division — that's what the deprecated `CLASS_TO_DIV` mapping did, and is the bug we fixed.

## `data_audit_results`

**Source:** `scripts/audit/__init__.py:run_full_audit()` — Phase 0 audit runs. One UUID `run_id` per invocation; persisted via `scripts/audit/report.py:persist_to_db()`. RLS-enabled (no anon access). See `reports/data_audit/SUMMARY.md` for the latest run's human-readable rollup.

## `game_predictions`

**Sources:**

- v1 validator runs (commits `61ee7bb`..`808b725`, May 2026): tagged `config_label IN ('baseline', 'phase-2a' .. 'phase-2e')`. DEPRECATED per v2 plan; kept as audit trail only.
- v2 walk-forward runs (TASK 4+ pending): will use `config_label LIKE 'wf-%-v2'`.

Baseball predictions were deleted 2026-05-25 ahead of the baseball re-scrape (FK cascade requirement); ~69K rows lost. All deleted predictions were v1-deprecated and not load-bearing.
