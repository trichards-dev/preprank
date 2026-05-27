# PrepRank Prediction Model — Formal Specification

*v2 TASK 3 (Phase 1) deliverable. Author: Reese-led, 2026-05-26. Status: Active.*

## Scope

This document is the contract that v2 Phase 4-6 work fits against. It defines:

1. The functional form of the game-prediction model (logit equation, feature definitions)
2. The fitting protocol (max-likelihood logistic regression on the train fold)
3. The per-sport vs global parameter split
4. The prior-year carryover decay schedule
5. The recalibration gate (Phase 6)
6. The output discipline that gates any external accuracy claim

This document does NOT define:

- The walk-forward fold structure — that lives in `packages/engine/src/engine/validator/walk_forward.py` and is locked at modified-(b): drop 2021, train [2022, 2023, 2024], validate [2025]. See `claude-memory/apps/preprank/decisions.md` 2026-05-26 "Regime-change handling: modified-(b) selected."
- Per-feature implementation modules — those land in Phase 4 (`prediction/features/log_margin.py`, `mercy_weighting.py`, `massey_od.py`, `prior_year_carryover.py`). Each feature ships its own behavioral spec; this doc only fixes the slot it occupies in the equation.
- Engine power-rating math — `packages/engine/src/engine/power_rating.py` is validated at Spearman ρ > 0.97 against LHSAA officials (commit `ed5172d`) and is upstream of this model. The output of `power_rating.calculate_all_ratings` feeds in as the `rating` input.

## The model

For game *g* with home team *h* and away team *a* in sport *s* in season-week *(y, w)*:

```
logit P(home wins) = β₀ˢ
                   + β₁ˢ · Δrating(g)
                   + β₂ˢ · HFA_indicator(g)
                   + β₃ˢ · Δf_margin(g)
                   + β₄ˢ · Δf_offdef(g)
                   + β₅ˢ · Δf_pyc(g, y, w)
```

where:

- `Δx(g) = x_home - x_away` (consistent signing throughout)
- All β coefficients are **per-sport** (superscript *s*); no cross-sport pooling
- All features are computed from data observable **strictly before game *g***; no in-game or post-game leakage
- The logistic link function: `P(home wins) = 1 / (1 + exp(−logit))`

### Feature definitions

#### Δrating — pre-game power rating differential

```
Δrating(g) = rating(h, y, w-1) − rating(a, y, w-1)
```

The engine's per-week rating, evaluated as of the end of week *w-1* (the week immediately preceding the game). For week 1 games, `Δrating` uses the prior season's final rating; if the team has no prior season's rating (cold start), see the cold-start handling section below.

This is the dominant signal. Baseline (Phase 3) uses Δrating alone; β₂..β₅ default to 0 in baseline and are unlocked one feature at a time across Phases 4a-4f.

**What the rating consumes (added 2026-05-27 after Phase 4c mechanism check):** The LHSAA engine power rating in `packages/engine/src/engine/power_rating.py` consumes **wins/losses + opponent W-L record + classification level only — it does NOT consume score margins.** Per `calculate_game_points` (L20-34): `result_points = 10 if won else 0` (boolean W/L), `play_up_points = 2 · play_up_levels` (classification only), `opponent_wins_points = (opp.wins / opp.games_played) · 10` (opponent W/L only). The iterative `calculate_all_ratings` loop (L92-127) reads only `won` and opponent records — scores never enter. **The engine rating is W/L+SoS-based, not margin-aware.** This matters for interpreting Phase 4c+ ablation results: any "Δrating already captures margin" reasoning is wrong; margin information enters the model only through dedicated margin features (β₃, β₆), never through β₁.

#### HFA_indicator — home-field advantage

```
HFA_indicator(g) = +1 if game is at home team's venue
                    0 if game is at a neutral site (e.g., jamboree, championship neutral)
                   -1 if "home" team is actually visiting (data error case; should never occur in clean data — flagged by audit check 0.6)
```

Per LHSAA Bulletin, postseason games above the regional level are at neutral sites. The audit's `games.neutral_site` flag (populated by ingest, value `True` for known neutral games) maps to indicator 0.

#### Δf_margin — log-compressed historical scoring margin (Phase 4c)

The home team's cumulative log-compressed margin signal minus the away team's:

```
f_margin(t, y, w) = mean over team t's games in [season_start, week w-1] of:
                       sign(team_score - opp_score) · ln(|team_score - opp_score| + 1)

Δf_margin(g) = f_margin(h, y, w) − f_margin(a, y, w)
```

The log compression mutes blowouts without discarding them (a 49-7 win contributes ln(43) ≈ 3.76 vs a 21-14 win's ln(8) ≈ 2.08 — informative ordering, less hostage to runaway scores). Scale parameter not needed because β₃ absorbs it.

Reference implementation: `prediction/features/log_margin.py` (landed 2026-05-27 during Phase 4c).

**β₃ disposition: currently pinned to 0** based on Phase 4c null finding (run_id `166c2ce7-356c-44f0-a865-ff3c470f8f61`, 2026-05-27). All 8 sports showed accuracy lift in the noise band (max +0.0017, no FDR-significance, 0/8 above the 2pp audit threshold). The β₃ slot adds no marginal predictive power above β₁·Δrating + β₆·Δf_recent_form. Mechanism: β₆ recent-form already absorbs margin information via its capped_margin signal (it IS a margin feature, just recency-weighted). β₃ is redundant with β₆, not with β₁ — β₁ is W/L+SoS-based and contains no margin info (see "What the rating consumes" above). The slot is preserved in the functional form for re-evaluation if the engine rating definition changes (e.g., a future rating system that consumes margins would shift this redundancy boundary).

#### Δf_offdef — Massey-style offense/defense decomposition (Phase 4d)

For each team, decompose season-to-date scoring into offensive strength (points produced above the league mean) and defensive strength (points allowed below the league mean) via least-squares Massey decomposition. The game-level feature is the home team's offense-vs-away-defense matchup minus the away team's offense-vs-home-defense matchup:

```
matchup(team_X_off, team_Y_def) = X_off_strength + Y_def_weakness
Δf_offdef(g) = matchup(h_off, a_def) − matchup(a_off, h_def)
```

Computed as of the end of week *w-1*. Cold-start handling per the dedicated section below. Reference implementation lands in `prediction/features/massey_od.py` during Phase 4d.

#### Δf_pyc — prior-year carryover (Phase 4e)

For week ∈ {1, 2, 3}, the team has too few in-season observations for the engine rating to have stabilized. The carryover term draws on the team's final rating from the prior season, decayed by week index:

```
decay(w) = max(0, 1 − (w − 1) · ⅓)    # week 1: 1.0, week 2: 0.667, week 3: 0.333, week ≥ 4: 0.0
prior_rating(t, y) = rating(t, y-1, end_of_season) if team t has prior-season data, else NaN
f_pyc(t, y, w) = decay(w) · prior_rating(t, y) if prior_rating present, else 0
Δf_pyc(g, y, w) = f_pyc(h, y, w) − f_pyc(a, y, w)
```

Crucially: the carryover is **additive to the engine rating**, not a replacement. By week 4 the carryover decays fully and Δrating carries the full signal. Weeks 1-3 are exactly the cold-start window where the engine rating is least informative — by design.

Cold-start without prior season: `f_pyc` returns 0 (no carryover available). The model still has Δrating, which the engine seeds at the league mean for cold-start teams; this is the regime where the model is weakest, surfaced explicitly in Phase 6's per-week reliability decomposition.

Reference implementation lands in `prediction/features/prior_year_carryover.py` during Phase 4e.

### Mercy-rule weighting (Phase 4c)

Phase 4c is NOT a new feature in the logit equation. It is a **per-game training weight** that down-weights games where the mercy rule was invoked (clock continuously running per LHSAA Bulletin §6.12.2's deflated-margin guidance). Mercy games carry weight `w_mercy ∈ [0, 1]` in the negative-log-likelihood loss; non-mercy games carry weight 1.0.

`w_mercy` is fitted per sport via the same protocol as the β vector (treated as an additional scalar parameter), constrained to `[0, 1]`. Reference implementation lands in `prediction/features/mercy_weighting.py` during Phase 4c.

**Volleyball schema deferral:** Volleyball mercy detection requires per-set point totals (option a: 3-0 sweep AND every set won by 8+; option b: total point differential ≥ 30). Our `games.home_score`/`away_score` for Volleyball stores sets-won (0-3) only, not per-set point totals. Until a re-scrape with per-set scores lands (post-launch v1.1), Volleyball mercy detection is limited to the **set-sweep approximation** (set-margin == 3); the spec's per-set point-total rule is the long-term target but is not enforceable on the current schema. This limitation must be disclosed in the Phase 7 limitations section.

### Recent form (Phase 4f)

Phase 4f explicitly tests whether overweighting recent games (e.g., last-3-games weight ×1.5 in the engine's rating computation) improves prediction. Per the v2 plan: "spec calls this last and warns it'll likely be redundant" — the engine's existing time-aware weighting already partially captures recency. Phase 4f either lands as a coefficient adjustment in the engine, OR as a separate Δf_recent_form term in the logit equation; the choice is deferred to Phase 4f's implementation.

If Phase 4f adds a new logit term, it becomes β₆ˢ · Δf_recent_form(g), extending the equation in the obvious way without invalidating fitted (β₀..β₅) on prior phases.

## Fitting protocol

### Loss function

Per-game weighted binary cross-entropy:

```
L(β) = − Σ_{g ∈ train} w_g · [ y_g · log(p_g(β)) + (1 − y_g) · log(1 − p_g(β)) ] + λ · ||β||₂²
```

where:
- `y_g ∈ {0, 1}` is the home-team outcome (1 if home won)
- `p_g(β)` is the model's predicted P(home wins) given β
- `w_g` is the per-game weight (1.0 for non-mercy games, `w_mercy` for mercy games during Phase 4c+)
- `λ` is the L2 regularization strength

### Regularization

L2 (ridge) regularization. The per-game λ is chosen via **k-fold nested CV inside the train fold** — never hardcoded. Default grid: `{1e-4, 1e-3, 1e-2, 1e-1, 1.0}` per-game (scaled by the inner-fold's `n_train_games` when added to the loss so the per-game contribution is constant across sports of different sample sizes). Default folds: 5. Selection criterion: mean held-out **unregularized** NLL across folds (regularization is a training tool, not a validation criterion).

The fitted λ for each sport is recorded in `FitResult.selected_lambda_per_game` and the full grid scores in `FitResult.lambda_cv_scores`, so every published β-vector is paired with its auditable λ provenance.

Tests + sanity runs may bypass nested CV by passing `l2_lambda_per_game` explicitly to `fit_sport` (used in unit tests + one-shot diagnostic re-fits). The walk-forward runner MUST NOT do this in production paths; bypass is a test-only escape hatch.

### Optimizer

`scipy.optimize.minimize` with `method='BFGS'`. Already transitively available in the engine's dependency graph (via scipy.stats / pandas / numpy chain); no new dependency. Initial values: all β = 0 (uninformed prior). Convergence: gtol=1e-6, maxiter=200. Failure: log + raise — no silent fallback to partial fit.

### Per-sport vs pooled parameters

Each sport fits its own (β₀..β₅) vector. No cross-sport pooling — football and baseball have meaningfully different score-distribution shapes and HFA magnitudes. The engine's power_rating step is sport-agnostic (same formula); divergence enters at this prediction layer.

### Cold-start handling

A team is "cold-start" for game *g* if it has fewer than 3 completed games in the current season AND has no prior-season rating. For cold-start teams, Δrating uses the seeded league-mean rating from the engine. The model is least accurate on cold-start games by design; Phase 6 explicitly reports per-cold-start accuracy and Brier so this regime is auditable.

### Numerical guarantees

- Predicted probabilities are clipped to `[1e-6, 1 − 1e-6]` before loss evaluation to prevent log(0) blowups
- Output probabilities for prediction (not loss) are NOT clipped — preserves resolution at extremes for the recalibration step
- Fitting fails loudly on non-finite gradients; the runner re-emits the failing game's feature vector in the error message

## Per-sport β-vector storage

Fitted β-vectors are stored in `PredictionConfig.model_coefficients_by_sport`:

```python
{
    "Football": {"beta_0": -0.043, "beta_1": 0.512, "beta_2": 0.401, ...},
    "Boys Basketball": {...},
    ...
}
```

with one dict per sport, keys `beta_0` through `beta_5` (or `beta_6` if Phase 4f adds a term). Missing-key behavior: any β not present in the dict is treated as 0.0. This is what makes baseline backward-compatible — an empty dict reduces the equation to logit = 0, then β₁ · Δrating is added by the engine's legacy path when no features are enabled.

Per-sport recalibration parameters (Phase 6, if applied) live in `PredictionConfig.recalibration_params_by_sport`, with method-specific JSON blobs (e.g., isotonic regression breakpoints).

## Phase 6 recalibration gate

The canonical baseline (`wf-baseline-v2`, run_id `2ac75c22-...`) showed systematic over-confidence at extremes: predicted 0.97 → observed 0.81, predicted 0.04 → observed 0.19. Phase 6 fits an isotonic regression on the train fold's (predicted, observed) pairs and applies it to the validation fold's predictions, **per sport**.

Recalibration is opt-in per sport. Trigger: calibration slope ∉ [0.85, 1.15] OR Brier score detectably degraded vs the isotonic-recalibrated alternative on the train fold (CI on Brier-delta with lower bound > 0.001). Per `claude-memory/apps/preprank/decisions.md` 2026-05-26 condition #2: **no external accuracy claim is published without recalibration applied** when the slope test triggers.

The isotonic implementation lives in `packages/engine/src/engine/validator/calibration.py` (already shipped per TASK 3 framework commit `9f4993e`). The fit is on raw predictions from this model; the recalibrated predictions are what flow into Phase 7 marketing-claim outputs.

## Output discipline (binding on TASK 3+)

Four conditions from `claude-memory/apps/preprank/decisions.md` 2026-05-26 "TASK 3 sign-off granted":

1. **No external accuracy numbers until residual Football Cat 1 is closed.** Tracked via `ReleaseMetadata.cat1_residual_closed`. Internal Phase 4-6 work proceeds regardless; publication-facing artifacts (Phase 7) call `assert_external_release_allowed` which blocks when this flag is False.
2. **No accuracy claims until Phase 6 recalibration is applied** when the calibration slope is outside [0.85, 1.15] for the sport. Tracked via `ReleaseMetadata.recalibration_required` + `recalibration_applied`; the gate blocks when required=True and applied=False.
3. **Marketing claims (Phase 7) rewritten for rigor positioning.** The phrase "beats professional benchmarks" (and similar) is prohibited from any artifact this model's outputs feed into. Enforced by `scan_for_prohibited_phrases` which raises `ReleaseGateError` on any match.
4. **Competitive-game stratification (Q1/Q2/Q3/Q4 by abs(Δrating)) computed before any Phase 7 work.** Tracked via `ReleaseMetadata.stratification_computed`. Q1 is the high-rating-gap (likely blowout) quartile; Q4 is the toss-up quartile.

### Mechanism-verification rule for "smoking gun" / "data drift" claims (added 2026-05-27)

Binding on every Phase report, every methodology disclosure, every external claims doc, and every internal phase-completion writeup that attributes an observed metric anomaly to a data-quality condition (NULL share, coverage gap, missing source, schema shift).

Before publishing a claim of that form, the report MUST include all four verification lines:

1. **Identify the specific code path that uses the data in question.** Grep result + file:line reference.
2. **Show evidence (code reference + value flow) that the data actually affects model predictions through that path.** Not the audit layer, not display logic, not fallback-only paths unless quantified as the dominant source.
3. **Quantify the maximum possible impact.** Form: "this affects at most N games out of M, so the maximum effect on accuracy is K percentage points."
4. **Confirm the maximum impact is consistent with the observed anomaly.** If the maximum impact (step 3) is materially smaller than the observed effect, the data condition cannot be the cause — walk the claim back in the same report.

Failed verifications walk back IN THE SAME report, not as a follow-up correction. This rule exists because two retracted "smoking gun" framings in five phases (Phase 1 75.5% football number; Phase 4b Boys Soccer 100%-NULL division) followed the same pattern: striking fact → causal story → smoking-gun label → mechanism check at later phase → retraction. The check must precede the label.

See `claude-memory/apps/preprank/decisions.md` 2026-05-27 "Mechanism-verification rule for 'smoking gun' / 'data drift' claims" for the originating context and the rule's verbatim form.

### Code-level enforcement points

These are not doc-only rules — they're enforced at three live code paths:

- **`engine.prediction.release_gate.assert_external_release_allowed(metadata)`** — every Phase-7 emitter calls this on its `ReleaseMetadata` before writing any artifact. Defaults are pessimistic (False/0.0) so an un-initialized metadata always blocks. Multiple failures aggregate in a single `ReleaseGateError`.
- **`engine.prediction.release_gate.scan_for_prohibited_phrases(text, source=...)`** — every Phase-7 emitter calls this on its full text body before writing. Matches are case-insensitive regex; the pattern list is in `release_gate.py` and is runtime-extensible via `add_prohibited_pattern`.
- **`engine.prediction.model.predict_game_v3(..., strict=True)`** — the walk-forward runner once a fit completes, and the Phase-7 marketing-claim generator, MUST set `strict=True`. When True and no fitted coefficients exist for the sport, raises `MissingCoefficientsError`. This is what prevents the legacy `win_probability_v2` fallback path from silently masquerading as a v2 fitted result. The `strict=False` default preserves the regression guarantee for legacy callers (existing engine consumers + scenarios router).

`packages/engine/tests/test_release_gate.py` covers each gate path; `test_model.py` covers the strict-mode gate.

## Implementation contract (TASK 3 deliverable 2/3)

`packages/engine/src/engine/prediction/model.py` provides:

```python
@dataclass
class GameState:
    rating: float
    margin_signal: float = 0.0
    off_signal: float = 0.0
    def_signal: float = 0.0
    prior_year_rating: float | None = None
    week_number: int = 1
    season_year: int = 0

@dataclass
class FitResult:
    sport: str
    coefficients: dict[str, float]
    n_train_games: int
    converged: bool
    loss: float
    iterations: int
    message: str = ""
    selected_lambda_per_game: float = 0.0       # CV-chosen λ
    lambda_cv_scores: dict[float, float] = ...  # per-grid-λ held-out NLL

class MissingCoefficientsError(RuntimeError): ...
class FitConvergenceError(RuntimeError): ...

def fit_sport(
    sport: str,
    train_games: Iterable[GameTrainingRow],
    *,
    l2_lambda_per_game: float | None = None,        # None ⇒ nested CV
    lambda_grid: Sequence[float] | None = None,
    cv_n_folds: int = 5,
    cv_seed: int = 0,
    mercy_weight: float = 1.0,
    max_iter: int = 200,
    gtol: float = 1e-6,
    initial_coefficients: Sequence[float] | None = None,
) -> FitResult: ...

def predict_game_v3(
    home_state: GameState,
    away_state: GameState,
    sport: str,
    config: PredictionConfig,
    *,
    is_neutral_site: bool = False,
    strict: bool = False,                            # raise vs fallback
) -> float: ...
```

`predict_game_v3` reads coefficients from `config.model_coefficients_by_sport[sport]`. If the dict is absent or empty for that sport AND `strict=False`, it falls back to the legacy `win_probability_v2` path — preserves the regression guarantee. If `strict=True`, it raises `MissingCoefficientsError` instead; v2 callers (the walk-forward runner, Phase-7 generator) MUST use `strict=True`.

Tests cover (all green in `packages/engine/tests/test_model.py` + `test_release_gate.py`):

- **Coefficient recovery on synthetic data**: 8,000 games with known β, per-coefficient tolerances calibrated to 95% sampling CI on Bernoulli noise (β₁ within 0.05, β₀/β₂ within 0.10)
- **Held-out prediction MAE**: fitted-model probabilities match data-generating probabilities within MAE < 0.02 on a 2,000-game held-out set
- **Default-config regression**: with empty `model_coefficients_by_sport`, `predict_game_v3` returns the same value (within float epsilon) as `win_probability_v2`
- **Strict-mode gate**: `strict=True` with empty coefficients raises `MissingCoefficientsError`
- **Bounded outputs**: `predict_game_v3` ∈ [0, 1] over a grid of pathological inputs (extreme Δrating saturates to 0.0 or 1.0; finite + bounded is the guarantee)
- **HFA polarity**: with β₂ > 0, the team labeled "home" gets a probability uplift; neutral-site eliminates it cleanly
- **Cold-start path**: `prior_year_rating = None` produces a finite prediction (β₅·Δf_pyc evaluates to 0, not NaN)
- **Nested CV**: default `fit_sport` path runs 5-fold CV over the λ grid, records per-λ held-out NLL, picks the minimum
- **CV determinism**: same `cv_seed` + same data ⇒ identical λ + identical fold scores
- **Recalibration application**: isotonic + Platt paths apply correctly; malformed params fall back to raw
- **Release-gate enforcement**: each of the four conditions (Cat 1, recalibration-when-required, stratification, prohibited phrases) raises `ReleaseGateError` when violated; multi-failure aggregation works; defaults are pessimistic

## Verification

Phase 1 sign-off requires all four:

1. This file exists at `docs/model_specification.md` — DONE
2. `packages/engine/src/engine/prediction/model.py` implements the contract above — DONE
3. `packages/engine/src/engine/prediction/config.py` extends with `model_coefficients_by_sport` and `recalibration_params_by_sport` — DONE
4. `packages/engine/src/engine/prediction/release_gate.py` implements code-level enforcement of the four output conditions — DONE
5. `pytest packages/engine/` is green — DONE (215 passed)

## Cross-references

- v2 plan (this doc operationalizes TASK 3 of it): `~/.claude/plans/do-number-2-eager-brook.md`
- Modified-(b) regime decision: `claude-memory/apps/preprank/decisions.md` 2026-05-26
- Output discipline (Cat 1 + recalibration + marketing + stratification): `claude-memory/apps/preprank/decisions.md` 2026-05-26 "TASK 3 sign-off granted"
- Cat 1 30-case diagnostic plan: `docs/cat1_30case_plan.md`
- Canonical baseline run (the artifact this model will be measured against): run_id `2ac75c22-121f-4f0c-99a5-f8c9099a7cfa`, `wf-baseline-v2`
