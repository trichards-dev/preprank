# Residual Football Cat 1 — 30-Case Diagnostic Plan

*Queued 2026-05-26 per Reese's TASK 3 sign-off conditions. Parallel to Phase 4-6 work; not on the critical path for internal modeling, but binding before any external accuracy claim leaves the office.*

## What we're answering

Post-OOS-fix Football Cat 1 sits at ~17.8% (2025), ~30.8% (2022), ~20.8% (2023) per the latest audit run (`58549021-8628-4b51-8424-d1de4acc2fac`). The OOS fix removed ~5-7pp; the residual is a *separate* scraper-completeness gap. Hypothesis (Reese, 2026-05-26): tournament games, forfeit games, and late-added games (LHSAA allows additions through the 8th playing date) account for the residual.

This diagnostic confirms or refutes that hypothesis by categorizing 30 specific Cat 1 cases.

## Methodology — mirror of the OOS diagnostic that landed 2026-05-25

The OOS diagnostic worked because the symptom (0% OOS rate across 85K games) had a single discoverable mechanism (the `continue` at line 432-438). For the residual Cat 1, no single bright-line line is expected — the residual is the *sum of several small mechanisms*. Categorization is the deliverable.

### Sample selection (n=30)

From the latest audit run's `data_audit_results.details` JSONB for `check_name='0.7_cross_source'`, Football only:

- **2025 stratum: 12 teams** — highest OOS-fix residual (17.79%), most policy-relevant for launch
- **2023 stratum: 10 teams** — second-largest residual (20.75%) and clean PDF coverage
- **2022 stratum: 8 teams** — third stratum to detect whether the cause is season-stable or season-specific

Within each stratum, pick teams in proportion to division mix in that season's PDF (Div I/II/III/IV roughly equal). Within division, pick deterministically (sort by team_id, pick every Nth) — no random sampling, so the diagnostic is reproducible.

Exclude teams already flagged by other audit checks (mercy-rule outliers, score-distribution outliers, team-game-balance failures) so we're isolating Cat 1 as the failure mode rather than confounding it with separately-known data quality issues.

### Per-team data pull

For each sampled team:

1. **Our DB games** — `SELECT game_date, week_number, home_team_id, away_team_id, opponent.school_id, opponent.school_name, opponent.parish, home_score, away_score, is_out_of_state FROM games JOIN teams ... WHERE (home_team_id = X OR away_team_id = X) AND season_year = S ORDER BY game_date`. Expected count: 9-10 regular season + 0-3 playoff per LHSAA Bulletin §14.12.3.
2. **PDF row** — parsed via `scripts/parse_lhsaa_pdf.py` from the snapshot PDF for that team-season-division. Carries W, L, T totals only (no opponent list).
3. **LHSAA team schedule page** — fetch + parse via the existing scraper module in `scripts/ingest_football_historical.py`'s per-team schedule loop, dumping the full schedule row HTML (not just the rows that survive ingest filtering).
4. **Diff** — schedule-row count vs our games count = the per-team Cat 1 gap. Each missing row is the unit of categorization.

### Categorization (5 buckets per missing row)

For each missing row from step 4:

| Bucket | Detection |
|---|---|
| (i) **Playoff/tournament** | Game date > regular-season end (LHSAA Football publishes the calendar; 2025 regular season ended Friday of Week 10). |
| (ii) **Forfeit** | Row contains `FORFEIT`, `FFT`, or score `1-0`/`0-1` with a marker; per LHSAA Bulletin §14.12.4 single forfeits ARE counted. |
| (iii) **Late-added** | Opponent appears on the LHSAA schedule page but not on the date our last ingest ran (compare `games.updated_at` max for the season to the row's date — if row date > max ingest date, late-add). |
| (iv) **Opponent fuzzy-match drop** | Opponent name in schedule row, but `_find_school_id()` returned None and the OOS-helper didn't tag it. Check our cached `unmatched_schools.log` for that ingest run. |
| (v) **Other** | Everything else — surface for spot-review. Likely candidates: scraper exception that swallowed one row, character-encoding fail on opponent name, week_number assignment edge case. |

### Output

- `reports/data_audit/cat1_30case/sample.json` — the 30 selected teams + per-team raw data dump (our games, PDF row, scraped schedule HTML row count)
- `reports/data_audit/cat1_30case/diffs.json` — per-team list of missing rows with bucket assignments
- `reports/data_audit/cat1_30case/SUMMARY.md` — table: bucket × count × example team. Top-line verdict:
  - **Hypothesis confirmed** if buckets (i)+(ii)+(iii) ≥ 70% of missing rows → scoped fix per cause
  - **Hypothesis partially confirmed** if 40-70% → name the dominant non-hypothesis bucket
  - **Hypothesis refuted** if <40% → re-open the root-cause question; bucket (v) names new candidates

### Decision after diagnostic

Per Reese's 2026-05-26 conditions, two acceptable outcomes:

- **Fixed** — for buckets where the cause is scoped and small (e.g., bucket (ii) forfeits = adjust score-format parser; bucket (iv) fuzzy-match = tighten the school-name index), implement the fix, re-scrape affected sport-seasons, re-run the audit, verify Cat 1 → target band.
- **Formally characterized** — for buckets where the cause is real but not worth fixing pre-launch (e.g., bucket (i) playoff games where our launch product doesn't predict playoff brackets anyway; bucket (iii) late-adds covered by post-launch re-ingest), document the bias direction and magnitude in the Phase 7 limitations section, with a quoted Cat 1 residual rate.

Either outcome unblocks external accuracy claims. Internal Phase 4-6 work is unaffected — Cat 1 affects the *trust framing* of the numbers, not the numbers themselves.

## Script skeleton (to implement when bandwidth allows)

```
scripts/audit/cat1_30case.py    # CLI entry: python -m scripts.audit.cat1_30case run --sport football --seasons 2022,2023,2025
  ├── select_sample(audit_run_id, sport, season_quotas) -> list[TeamSample]
  ├── pull_our_games(team_id, season) -> list[GameRow]              # supabase REST
  ├── pull_pdf_row(team_id, season) -> PdfRow                       # reuse parse_lhsaa_pdf
  ├── pull_schedule_html(team_id, season) -> list[ScheduleRow]      # reuse ingest_football_historical scrape primitive
  ├── diff(our_games, schedule) -> list[MissingRow]
  ├── categorize(missing_row, context) -> Literal["playoff","forfeit","late_add","fuzzy","other"]
  └── write_outputs(sample, diffs, summary) -> None
```

Estimated time: ~6 hours implementation + ~30 min execution. Designed to slot into the first Phase-4 sign-off cycle without breaking phase isolation.

## What this is NOT

- Not a tool for ongoing monitoring — that's the regular `0.7_cross_source` check
- Not a re-litigation of Phase 0 cross-source methodology — uses the same Cat 1 definition
- Not blocking on TASK 3 framework code, the canonical baseline, or any Phase 4-6 phase

## Cross-references

- Methodology origin: OOS diagnostic at `reports/data_audit/cat1_diagnostic/RESULTS.md` (2026-05-25)
- Audit run referenced: `58549021-8628-4b51-8424-d1de4acc2fac` (latest post-OOS-fix)
- Open question entry: `claude-memory/apps/preprank/open-questions.md` "2026-05-26 — Cat 1 30-case diagnostic queued"
- Sign-off conditions: `claude-memory/apps/preprank/decisions.md` "2026-05-26 — TASK 3 sign-off granted"
