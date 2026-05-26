# PrepRank — Methodology Disclosure (DRAFT, internal)

*Status: DRAFT for Phase 7 review. NOT FOR EXTERNAL PUBLICATION. Date: 2026-05-26.*

*This is the source-of-truth disclosure paragraph PrepRank uses anywhere it makes a per-sport accuracy or Brier claim. Marketing site copy, app legal/transparency screens, store-listing fine print, and any press communication draw from this. Edits to this file gate the corresponding edits in downstream surfaces.*

---

## How we measured

PrepRank's predictive numbers come from a single walk-forward validation run. We dropped 2021 from the corpus because LHSAA Football's 2022 reclassification changes the division structure in ways that would contaminate training. We trained per-sport on 2022–2024 game outcomes and validated on 2025 — one fold, ~52,000 train games, ~18,000 validation games across eight sports.

For each sport we fit a logistic-regression model with intercept, pre-game power-rating differential, home-field indicator, log-compressed scoring margin, an offense/defense decomposition, and a prior-year-rating carryover term decayed over weeks 1–3 of the new season. Coefficients were fit by L2-regularized maximum likelihood. The L2 strength was chosen by 5-fold nested cross-validation **inside the train fold** — not picked once on the holdout. Phase 6 reliability auditing (per-decile predicted-vs-observed) runs on every published metric; recalibration is applied when the per-sport calibration slope falls outside [0.85, 1.15] or when per-decile tail bins show miscalibration that survives the calibration-slope summary.

Every per-sport accuracy and Brier number we publish carries a 95% confidence interval from 1000-resample paired bootstrap on the holdout fold. Per-feature comparisons across the 8 sports' independent decisions are corrected for multiple comparisons via Benjamini-Hochberg FDR at α = 0.05.

## Known limitations of the underlying data

LHSAA does not publish a single canonical schedule; we assemble ours from `lhsaaonline.org` schedule pages. Our 2026-05-26 audit shows residual cross-source coverage gaps against LHSAA's published Power Rating PDFs:

- **Per-season Cat 1 rate (Football, post-OOS-fix):** 2022 = 29.7%, 2023 = 20.7%, 2025 = 17.4%. "Cat 1" = teams where LHSAA's published game count exceeds our database's count.
- **Dominant gap pattern (93.3% of sampled cases):** a team is short by 1–2 games in our database, with most or all 10 regular-season weeks otherwise covered. The shortfall concentrates in specific (team, week) cells — typically one week missing per team — suggesting opponent-matching failures for individual games rather than wholesale scrape drops.
- **Secondary patterns (6.7% of sampled cases):** specific weeks missing entirely from a team's record, consistent with intermittent scraper failures.
- **Anomaly worth disclosure:** LHSAA's published Division I Select 2025 Power Rating PDF lists 12 regular-season games for three teams (St. Paul's, Bonnabel, Comeaux), where Bulletin §14.12.3 implies a 10-game cap. This is the LHSAA-side row count, not a database error on our side, but the discrepancy is not yet reconciled.

These coverage gaps mean a team's PrepRank rating reflects ~95–99% of the games LHSAA itself counts. Direction of bias: our power ratings are computed on a slightly smaller game set than the LHSAA officials they're benchmarked against, which typically dampens rating extremes (teams look fractionally closer to the league mean than they would on a complete sample).

## Where we explicitly do not cover

PrepRank does not model:
- Player injuries or eligibility status
- Coaching changes mid-season
- Weather effects on individual games
- Officiating, suspension, or disciplinary outcomes
- Travel distance or rest-day differentials between matchups

These limitations are inherent to a corpus that doesn't include injury or roster data. We do not infer them or impute them silently.

## Validation against LHSAA's official Power Ratings

The PrepRank engine power-rating step is independently validated against LHSAA's officially-published Power Ratings via Spearman rank correlation. For Football 2022 / 2023 / 2025, ρ = 0.977 / 0.987 / 0.989 across 288–298 matched teams; all four 2025 divisions individually ρ > 0.98. Non-football sports are validated to varying degrees as PDF coverage allows.

## What we do not say

PrepRank does not claim to "beat professional benchmarks." NFL prediction accuracy, MLB prediction accuracy, NBA tournament accuracy, and club-soccer accuracy are noted in our internal benchmark file purely as **context** for what predictive accuracy means in different sport regimes — not as targets PrepRank is beating. High school football's seasonal structure (10 regular-season games, weekly turnover, no shared roster databases across years) is a different statistical regime from professional leagues.

---

*Disclosure paragraph version control: this file. Any downstream surface that quotes per-sport accuracy or Brier must link back to this exact version. Phase-7 review will produce v1; everything before v1 is draft.*
