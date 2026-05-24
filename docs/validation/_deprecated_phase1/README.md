# Deprecated — Phase 1 validation work

The validation artifacts in this directory and `../_deprecated_phase1_fitted_params.json` are from the **Phase 1 validation** shipped 2026-05-23/24 (commits `61ee7bb`..`808b725`).

**These numbers are not to be quoted, displayed, or referenced externally.** They are preserved for git-history clarity and as audit context for the Phase 2 (v2) re-validation work.

## Why deprecated

Phase 1 had methodology gaps that Phase 2 corrects:

- Single train/holdout split was contaminated by 6 tuning decisions against the 2025 season
- Decision triggers used raw point thresholds, not 95% CI lower bounds
- No FDR correction across the 40 sport × phase tests
- No competitive-game stratification (whole-season averages mix blowouts with toss-ups)
- 6 of 8 sports missed Brier targets with no calibration deep-dive
- A baseball home/away data bug was found only because Phase 2c happened to fit an absurd HFA — i.e., by accident, not by design

See `/Users/reeserichards/.claude/plans/do-number-2-eager-brook.md` for the v2 plan that replaces this work.

## Headline Phase 1 numbers (frozen, do not quote)

- Football: 75.5% game-winner accuracy, Brier 0.215
- Girls Basketball: 76.8% / 0.190
- Overall: 70.9% / 0.238 across 8 sports × 5 seasons holdout

The v2 walk-forward re-run will produce new headline numbers with proper 95% CIs and competitive-game stratification. Until those are published, no external accuracy claims from this app.

## DB rows tagged with Phase 1 config_labels

The `game_predictions` table contains rows tagged `config_label='baseline'`, `'phase-2a'`, `'phase-2b'`, `'phase-2c'`, `'phase-2d'`, `'phase-2e'`. These rows stay in the DB as audit trail. v2 walk-forward runs will use distinct labels (`wf-baseline-fold3-v2`, `wf-phase4b-fold2-v2`, etc.) so v1 and v2 results never co-mingle in queries.
