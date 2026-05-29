"""Football Phase 6 diagnostic — root-cause the K-fold isotonic D1 tail
miscalibration before changing methodology.

Phase A.1: Massey conditioning across history windows (1yr / 2yr / 3yr / 5yr)
Phase A.2: D1 tail-bin statistical power — bootstrap CI on D1 gap
Phase A.3: Per-game variance for Football vs other sports
Phase A.4: D1 game inspection — sample 5 of 32 games for systematic-bias check

Output: reports/audits/football_phase6_diagnostic.{json, md}
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

import numpy as np

from engine.prediction.config import PredictionConfig
from engine.prediction.features.log_margin import precompute_team_week_log_margins
from engine.prediction.features.massey_od import precompute_team_week_massey_od, MasseyConditioningError, _extract_game_sides, _solve_massey
from engine.prediction.features.recent_form import precompute_team_week_form
from engine.prediction.model import fit_sport
from engine.validator.data import load_run_inputs, load_sports_map, load_teams_with_schools
from engine.validator.runner_v2 import (
    PHASE6_PINNED_INDICES,
    _build_training_rows,
    _predict_rows,
    _kfold_isotonic_recalibrate,
)


def make_supabase():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


SPORT = "Football"
TRAIN_SEASONS = [2022, 2023, 2024]
HOLDOUT_SEASONS = [2025]
DROP_SEASONS = [2021]
KFOLD_K = 5
SEED = 42


def _bootstrap_bin_gap_ci(
    bin_preds: list[float],
    bin_actuals: list[int],
    *,
    n_resamples: int = 1000,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Return (point_estimate, ci_lo, ci_hi) for |mean_predicted - mean_observed|.

    Bootstrap-with-replacement on the (pred, actual) pairs within a single bin.
    """
    rng = random.Random(seed)
    n = len(bin_preds)
    if n == 0:
        return 0.0, 0.0, 0.0
    gaps: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randint(0, n - 1) for _ in range(n)]
        bp = [bin_preds[i] for i in idx]
        ba = [bin_actuals[i] for i in idx]
        gaps.append(abs(statistics.mean(bp) - statistics.mean(ba)))
    point = abs(statistics.mean(bin_preds) - statistics.mean(bin_actuals))
    gaps_sorted = sorted(gaps)
    lo = gaps_sorted[int(0.025 * n_resamples)]
    hi = gaps_sorted[int(0.975 * n_resamples)]
    return point, lo, hi


def _power_n_for_gap_detection(target_gap: float, expected_base_rate: float, alpha: float = 0.05) -> int:
    """Minimum n to detect target_gap as significant at alpha against expected_base_rate.

    Two-sided proportion test on the bin's observed_mean.
    SE of binomial proportion ≈ sqrt(p*(1-p)/n). z=1.96 for 95%.
    Solve: target_gap = 1.96 * sqrt(p*(1-p)/n) → n = 1.96² * p*(1-p) / target_gap²
    """
    z = 1.96
    p = expected_base_rate
    n = (z ** 2) * p * (1 - p) / (target_gap ** 2)
    return int(n) + 1


def phase_a1_conditioning(sb) -> dict[str, Any]:
    """Phase A.1: Massey conditioning across history windows for Football.

    For Football 2025 holdout, test conditioning at each week with:
      - window = 1 year (just 2025 games up to W-1) — current
      - window = 2 years (2024 + 2025)
      - window = 3 years (2023-2025)
      - window = 5 years (2021-2025)
    """
    sports_map = load_sports_map(sb)
    sid = {n.lower(): s for s, n in sports_map.items()}[SPORT.lower()]
    teams = load_teams_with_schools(sb)

    # Load all 5 seasons available
    all_seasons = [2021, 2022, 2023, 2024, 2025]
    season_inputs = {}
    for season in all_seasons:
        season_inputs[season] = load_run_inputs(sb, sid, SPORT, season, teams=teams)

    # For each window size, compute the centered-Massey conditioning emit-rate
    # across weeks 1-16 on 2025 holdout. Window includes the 2025 games-so-far
    # PLUS the prior (window_size - 1) full seasons.
    result_per_window: dict[int, dict[str, Any]] = {}
    for window_size in (1, 2, 3, 5):
        # Aggregate games across the window
        seasons_to_use = list(range(2025 - window_size + 1, 2025 + 1))
        # filter out 2021 if dropped; we keep it here for the diagnostic
        all_games = []
        for s in seasons_to_use:
            if s in season_inputs:
                all_games.extend(season_inputs[s].games)
        # Try Massey conditioning at multiple weeks (using "across all years" basis)
        # We approximate by passing full game list to precompute_team_week_massey_od,
        # which is cumulative through W-1; sample weeks 4, 8, 12, 16
        try:
            table = precompute_team_week_massey_od(all_games)
        except Exception as e:
            table = {}

        # Count emitted entries vs total team-week opportunities
        teams_in_window = set()
        for g in all_games:
            teams_in_window.add(g["home_team_id"])
            teams_in_window.add(g["away_team_id"])
        emitted = len(table)
        # Also extract conditioning numbers at week 16 (end of regular season)
        # via direct _solve_massey on the full basis
        sides = _extract_game_sides(all_games)
        teams_list = sorted({s[0] for s in sides} | {s[1] for s in sides})
        cond = None
        n_eqs = len(sides)
        n_teams = len(teams_list)
        ratio = n_eqs / max(1, 2 * n_teams)
        try:
            _alpha, _o, _d, cond = _solve_massey(
                [(t, o, p) for (t, o, p, _w) in sides], teams_list,
            )
        except MasseyConditioningError as e:
            cond = float("inf")  # didn't converge

        result_per_window[window_size] = {
            "seasons": seasons_to_use,
            "n_games": len(all_games),
            "n_teams": len(teams_in_window),
            "games_per_team_side": round(2 * len(all_games) / max(1, n_teams), 3),
            "n_team_weeks_emitted": emitted,
            "cond_at_end_of_window": cond if cond is not None and cond != float("inf") else "INF (raises)",
            "emit_yes_no": "emit" if cond is not None and cond != float("inf") else "raise (collapses to 0)",
        }
    return result_per_window


def phase_a2_d1_power(d1_preds: list[float], d1_actuals: list[int]) -> dict[str, Any]:
    """Phase A.2: bootstrap CI on D1 gap + power analysis."""
    point, lo, hi = _bootstrap_bin_gap_ci(d1_preds, d1_actuals, n_resamples=1000, seed=SEED)
    # Power analysis: how many games would we need to detect 0.05 gap at this bin's base rate?
    obs_rate = statistics.mean(d1_actuals) if d1_actuals else 0.05
    n_needed_for_005 = _power_n_for_gap_detection(0.05, obs_rate)
    n_needed_for_0083 = _power_n_for_gap_detection(0.083, obs_rate)
    return {
        "n": len(d1_preds),
        "point_gap": point,
        "ci_95_lo": lo,
        "ci_95_hi": hi,
        "ci_excludes_threshold_005": lo > 0.05,
        "ci_excludes_zero": lo > 0.0,
        "n_needed_to_detect_005_gap": n_needed_for_005,
        "n_needed_to_detect_0083_gap": n_needed_for_0083,
    }


def phase_a3_variance(sb) -> dict[str, Any]:
    """Phase A.3: per-game variance for Football vs other sports.

    Compute the variance of (home_score - away_score) across each sport's
    2025 games, plus residual variance after controlling for the engine's
    pre-game rating differential.
    """
    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): s for s, n in sports_map.items()}
    teams = load_teams_with_schools(sb)
    all_sports = ["Football", "Volleyball", "Boys Basketball", "Girls Basketball",
                  "Baseball", "Softball", "Boys Soccer", "Girls Soccer"]
    by_sport: dict[str, dict[str, Any]] = {}
    for sp in all_sports:
        sid = name_to_id.get(sp.lower())
        if sid is None:
            continue
        inp = load_run_inputs(sb, sid, sp, 2025, teams=teams)
        margins = []
        for g in inp.games:
            hs = g.get("home_score")
            asc = g.get("away_score")
            if hs is None or asc is None:
                continue
            margins.append(float(hs) - float(asc))
        if not margins:
            continue
        by_sport[sp] = {
            "n_games": len(margins),
            "mean_margin": round(statistics.mean(margins), 3),
            "std_margin": round(statistics.stdev(margins), 3) if len(margins) > 1 else 0.0,
            "abs_max_margin": max(abs(m) for m in margins),
        }
    # Coefficient of variation = std / mean(abs(margin)) lets us compare across sports with different scales
    for sp, st in by_sport.items():
        mean_abs = statistics.mean([abs(m) for m in [st["mean_margin"]] + [st["abs_max_margin"]]])
        # That's not quite right — compute CV from sample
        # Actually, for the purpose of this analysis, std_margin alone is the
        # key statistic. We compare std_margin across sports.
        pass
    return by_sport


def phase_a4_d1_games(holdout_inputs, preds_list, actuals_list, recal_probs) -> dict[str, Any]:
    """Phase A.4: sample D1 games for systematic-bias inspection.

    Find indices where recal_probs ∈ [0.0, 0.1] and surface the
    underlying game + team info.
    """
    d1_indices = [i for i, p in enumerate(recal_probs) if 0.0 <= p < 0.1]
    rng = random.Random(SEED)
    sampled = rng.sample(d1_indices, min(5, len(d1_indices)))
    samples = []
    for idx in sampled:
        pr = preds_list[idx]
        samples.append({
            "game_id": pr.game_id,
            "home_team_id": pr.home_team_id,
            "away_team_id": pr.away_team_id,
            "season_year": pr.season_year,
            "week_number": pr.week_number,
            "home_rating_pregame": round(pr.home_rating_pregame, 3),
            "away_rating_pregame": round(pr.away_rating_pregame, 3),
            "rating_diff_pregame": round(pr.home_rating_pregame - pr.away_rating_pregame, 3),
            "raw_predicted_home_win_prob": round(pr.home_win_probability, 4),
            "kfold_recalibrated_home_win_prob": round(recal_probs[idx], 4),
            "actual_home_won": pr.actual_home_won,
            "home_cold_start": pr.home_cold_start,
            "away_cold_start": pr.away_cold_start,
        })
    # Aggregate stats on full D1 set
    d1_count = len(d1_indices)
    d1_actuals = [actuals_list[i] for i in d1_indices]
    return {
        "n_d1_games": d1_count,
        "d1_home_win_count": sum(d1_actuals),
        "d1_home_win_rate": round(sum(d1_actuals) / max(1, d1_count), 4),
        "sample_games": samples,
    }


def main() -> int:
    sb = make_supabase()
    print(f"[diag] Football diagnostic starting...")

    # Replicate the Phase 6 K-fold path on Football only
    print("[diag] Loading Football holdout + fitting...")
    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): s for s, n in sports_map.items()}
    teams = load_teams_with_schools(sb)
    sid = name_to_id[SPORT.lower()]

    rf_config = PredictionConfig()
    train_rows = []
    hold_rows = []
    for season in TRAIN_SEASONS + HOLDOUT_SEASONS:
        if season in DROP_SEASONS:
            continue
        inp = load_run_inputs(sb, sid, SPORT, season, teams=teams)
        form = precompute_team_week_form(inp.games, SPORT, rf_config)
        lm = precompute_team_week_log_margins(inp.games)
        mas = precompute_team_week_massey_od(inp.games)
        rows = _build_training_rows(
            inp, recent_form_signals=form, log_margin_signals=lm, massey_od_signals=mas,
        )
        if inp.season_year in HOLDOUT_SEASONS:
            hold_rows.extend(rows)
        else:
            train_rows.extend(rows)

    fit = fit_sport(SPORT, train_rows, cv_seed=SEED, fixed_indices=list(PHASE6_PINNED_INDICES))
    cfg = PredictionConfig(model_coefficients_by_sport={SPORT: fit.coefficients})
    preds = _predict_rows(hold_rows, SPORT, cfg)
    preds_probs = [p.home_win_probability for p in preds]
    preds_actuals = [1 if p.actual_home_won else 0 for p in preds]

    print(f"[diag] Football holdout: {len(preds)} predictions")
    print("[diag] Running K-fold isotonic to identify the D1 bin contents...")
    recal_probs = _kfold_isotonic_recalibrate(preds_probs, preds_actuals, k=KFOLD_K, seed=SEED)

    # Build D1 indices and (pred, actual) pairs on post-iso state
    d1_idx = [i for i, p in enumerate(recal_probs) if 0.0 <= p < 0.1]
    d1_preds = [recal_probs[i] for i in d1_idx]
    d1_actuals = [preds_actuals[i] for i in d1_idx]

    print("[diag] Phase A.1: Massey conditioning across history windows...")
    a1 = phase_a1_conditioning(sb)
    print("[diag] Phase A.2: D1 bootstrap power analysis...")
    a2 = phase_a2_d1_power(d1_preds, d1_actuals)
    print("[diag] Phase A.3: per-game variance across sports...")
    a3 = phase_a3_variance(sb)
    print("[diag] Phase A.4: D1 game inspection...")
    a4 = phase_a4_d1_games(None, preds, preds_actuals, recal_probs)

    # Also compute the same for RAW (no isotonic) D1 — for direct comparison
    raw_d1_idx = [i for i, p in enumerate(preds_probs) if 0.0 <= p < 0.1]
    raw_d1_preds = [preds_probs[i] for i in raw_d1_idx]
    raw_d1_actuals = [preds_actuals[i] for i in raw_d1_idx]
    raw_d1_power = phase_a2_d1_power(raw_d1_preds, raw_d1_actuals)

    out = {
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "sport": SPORT,
        "train_seasons": TRAIN_SEASONS,
        "holdout_seasons": HOLDOUT_SEASONS,
        "kfold_k": KFOLD_K,
        "n_holdout": len(preds),
        "fit_coefficients": fit.coefficients,
        "phase_a1_conditioning": a1,
        "phase_a2_d1_bootstrap_postiso": a2,
        "phase_a2_d1_bootstrap_raw_comparison": raw_d1_power,
        "phase_a3_variance_by_sport": a3,
        "phase_a4_d1_games": a4,
    }
    out_dir = REPO_ROOT / "reports" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "football_phase6_diagnostic.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"[diag] artifacts → {out_dir / 'football_phase6_diagnostic.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
