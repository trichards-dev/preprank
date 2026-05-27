"""Phase 4d Step 1 — Ridge sensitivity diagnostic (Girls Soccer).

Reese 2026-05-27 evening sign-off after Phase 4d M3 conditioning flag:

    Step 1: Re-run Girls Soccer Phase 4d fit at ridge ∈ {1e-6, 1e-4,
    1e-2}. Report acc lift at each value; top-3 / bottom-3 Girls Soccer
    teams by (offense - defense) composite at end-of-season at each
    ridge; correlation of P(home_wins) predictions on the 20 audit
    games between ridge=1e-6 and ridge=1e-2.

    Decision criterion (logged BEFORE the run):
    - If acc lift stays within ±0.005 of original +0.1105 across all
      three ridge values AND rankings are largely stable: predictions
      robust, signal is "real" in a predictive sense. Proceed to Step 2.
    - If acc lift drops by >0.02 at higher ridge OR rankings reshuffle
      materially: ridge-artifact suspected. Document and proceed to
      Step 2 regardless (structural fix needed either way).

Output: reports/audits/phase4d_step1_ridge_sensitivity.{md,json}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

import numpy as np

from engine.prediction.config import PredictionConfig
from engine.prediction.features.log_margin import precompute_team_week_log_margins
from engine.prediction.features.massey_od import precompute_team_week_massey_od
from engine.prediction.features.recent_form import precompute_team_week_form
from engine.prediction.model import fit_sport, predict_game_v3
from engine.validator.data import (
    load_run_inputs,
    load_sports_map,
    load_teams_with_schools,
)
from engine.validator.metrics import game_winner_accuracy
from engine.validator.runner_v2 import (
    PHASE4_PINNED_INDICES,
    _build_training_rows,
    _predict_rows,
)


SPORT = "Girls Soccer"
TRAIN_SEASONS = [2022, 2023, 2024]
HOLDOUT_SEASONS = [2025]
DROP_SEASONS = [2021]
RIDGE_VALUES = [1e-6, 1e-4, 1e-2]
ORIGINAL_LIFT = 0.1105
LIFT_TOL = 0.005


def make_supabase():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def run_one_ridge(
    ridge: float,
    inputs_train: list,
    inputs_hold: list,
    sport: str,
    rf_config: PredictionConfig,
) -> dict:
    """Run Phase 4d fit + holdout eval at one ridge value. Return everything
    we need for the sensitivity comparison: lift, fitted coefficients,
    Massey ratings at end-of-season, and per-game holdout predictions.
    """
    # Build train + hold rows with Massey computed at this ridge
    train_rows = []
    hold_rows = []
    massey_table_by_season = {}
    for inp in inputs_train + inputs_hold:
        form_table = precompute_team_week_form(inp.games, sport, rf_config)
        log_margin_table = precompute_team_week_log_margins(inp.games)
        massey_table = precompute_team_week_massey_od(inp.games, ridge=ridge)
        massey_table_by_season[inp.season_year] = massey_table
        rows = _build_training_rows(
            inp,
            recent_form_signals=form_table,
            log_margin_signals=log_margin_table,
            massey_od_signals=massey_table,
        )
        if inp.season_year in HOLDOUT_SEASONS:
            hold_rows.extend(rows)
        else:
            train_rows.extend(rows)

    # Reference: β₃ pinned, β₄ free
    fit_b = fit_sport(sport, train_rows, cv_seed=42,
                       fixed_indices=list(PHASE4_PINNED_INDICES))
    # Ablation: β₃ AND β₄ pinned
    fit_a = fit_sport(sport, train_rows, cv_seed=42,
                       fixed_indices=list(PHASE4_PINNED_INDICES) + [4])

    config_b = PredictionConfig(model_coefficients_by_sport={sport: fit_b.coefficients})
    config_a = PredictionConfig(model_coefficients_by_sport={sport: fit_a.coefficients})

    preds_b = _predict_rows(hold_rows, sport, config_b)
    preds_a = _predict_rows(hold_rows, sport, config_a)

    b_acc = game_winner_accuracy(preds_b)
    a_acc = game_winner_accuracy(preds_a)
    acc_lift = b_acc - a_acc

    # Massey end-of-season ratings (latest week available per team)
    massey_2025 = massey_table_by_season.get(2025, {})
    latest_per_team: dict[int, tuple[int, tuple[float, float]]] = {}
    for (team_id, w), (o, d) in massey_2025.items():
        prev = latest_per_team.get(team_id)
        if prev is None or w > prev[0]:
            latest_per_team[team_id] = (w, (o, d))

    end_of_season = {team_id: (val[1][0], val[1][1]) for team_id, val in latest_per_team.items()}

    return {
        "ridge": ridge,
        "fit_baseline_coefficients": dict(fit_b.coefficients),
        "fit_ablation_coefficients": dict(fit_a.coefficients),
        "baseline_accuracy": b_acc,
        "ablation_accuracy": a_acc,
        "accuracy_lift": acc_lift,
        "n_train_rows": len(train_rows),
        "n_hold_rows": len(hold_rows),
        "end_of_season_massey": end_of_season,
        "preds_b": [p.home_win_probability for p in preds_b],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="reports/audits")
    args = ap.parse_args()

    sb = make_supabase()
    teams = load_teams_with_schools(sb)
    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    sport_id = name_to_id[SPORT.lower()]

    print(f"[step1] loading {SPORT} train + holdout...")
    inputs_train = [
        load_run_inputs(sb, sport_id, SPORT, s, teams=teams)
        for s in TRAIN_SEASONS
    ]
    inputs_hold = [
        load_run_inputs(sb, sport_id, SPORT, s, teams=teams)
        for s in HOLDOUT_SEASONS
    ]
    print(f"   train seasons: {[len(i.games) for i in inputs_train]} games each")
    print(f"   hold seasons:  {[len(i.games) for i in inputs_hold]} games each")

    rf_config = PredictionConfig()

    results = []
    for ridge in RIDGE_VALUES:
        print()
        print(f"[step1] running ridge = {ridge:.0e}...")
        r = run_one_ridge(ridge, inputs_train, inputs_hold, SPORT, rf_config)
        print(f"   baseline_acc = {r['baseline_accuracy']:.4f}")
        print(f"   ablation_acc = {r['ablation_accuracy']:.4f}")
        print(f"   acc_lift     = {r['accuracy_lift']:+.4f}")
        print(f"   β₄ baseline  = {r['fit_baseline_coefficients']['beta_4']:+.4f}")
        results.append(r)

    # ---------------------------------------------------------------------------
    # Rankings comparison: top-3 / bottom-3 by (offense - defense) composite
    # at end-of-season, per ridge value
    # ---------------------------------------------------------------------------
    team_name_lookup = {}
    for tid, info in teams.items():
        team_name_lookup[tid] = info.get("school_name") or info.get("name") or f"team_{tid}"

    rankings_per_ridge = {}
    for r in results:
        comp = {tid: (o - d) for tid, (o, d) in r["end_of_season_massey"].items()}
        sorted_teams = sorted(comp.items(), key=lambda kv: kv[1], reverse=True)
        rankings_per_ridge[str(r["ridge"])] = sorted_teams

    # Top-3 / bottom-3 at each ridge
    summaries = {}
    for ridge_str, sorted_teams in rankings_per_ridge.items():
        if not sorted_teams:
            summaries[ridge_str] = {"top_3": [], "bottom_3": []}
            continue
        top_3 = [
            {"team_id": tid, "name": team_name_lookup.get(tid, f"team_{tid}"),
             "composite": comp}
            for tid, comp in sorted_teams[:3]
        ]
        bottom_3 = [
            {"team_id": tid, "name": team_name_lookup.get(tid, f"team_{tid}"),
             "composite": comp}
            for tid, comp in sorted_teams[-3:][::-1]
        ]
        summaries[ridge_str] = {"top_3": top_3, "bottom_3": bottom_3}

    # ---------------------------------------------------------------------------
    # Stability: rank correlation between ridge=1e-6 and ridge=1e-2 rankings
    # ---------------------------------------------------------------------------
    rid_lo = str(RIDGE_VALUES[0])  # 1e-6
    rid_hi = str(RIDGE_VALUES[-1])  # 1e-2
    sorted_lo = rankings_per_ridge[rid_lo]
    sorted_hi = rankings_per_ridge[rid_hi]
    rank_lo = {tid: rank for rank, (tid, _) in enumerate(sorted_lo)}
    rank_hi = {tid: rank for rank, (tid, _) in enumerate(sorted_hi)}
    common = sorted(set(rank_lo) & set(rank_hi))
    if len(common) >= 3:
        x = np.array([rank_lo[t] for t in common])
        y = np.array([rank_hi[t] for t in common])
        rank_pearson = float(np.corrcoef(x, y)[0, 1])
        # Spearman is the rank-Pearson, so this is in fact Spearman
    else:
        rank_pearson = None

    # ---------------------------------------------------------------------------
    # Prediction correlation: P(home_wins) between ridge=1e-6 and ridge=1e-2
    # ---------------------------------------------------------------------------
    preds_lo = np.array(results[0]["preds_b"])
    preds_hi = np.array(results[-1]["preds_b"])
    if len(preds_lo) == len(preds_hi) and len(preds_lo) >= 2:
        pred_pearson = float(np.corrcoef(preds_lo, preds_hi)[0, 1])
        pred_max_abs_diff = float(np.abs(preds_lo - preds_hi).max())
        pred_mean_abs_diff = float(np.abs(preds_lo - preds_hi).mean())
    else:
        pred_pearson = None
        pred_max_abs_diff = None
        pred_mean_abs_diff = None

    # ---------------------------------------------------------------------------
    # Decision criterion evaluation
    # ---------------------------------------------------------------------------
    lifts = [r["accuracy_lift"] for r in results]
    max_lift_swing = max(lifts) - min(lifts)
    abs_diff_from_original = max(abs(l - ORIGINAL_LIFT) for l in lifts)

    # Rank-stability: top-3 and bottom-3 mostly unchanged across ridge values?
    top3_lo = {t["team_id"] for t in summaries[rid_lo]["top_3"]}
    top3_hi = {t["team_id"] for t in summaries[rid_hi]["top_3"]}
    top3_intersect = len(top3_lo & top3_hi)
    bot3_lo = {t["team_id"] for t in summaries[rid_lo]["bottom_3"]}
    bot3_hi = {t["team_id"] for t in summaries[rid_hi]["bottom_3"]}
    bot3_intersect = len(bot3_lo & bot3_hi)

    rankings_stable = (top3_intersect >= 2) and (bot3_intersect >= 2)
    lift_robust = abs_diff_from_original <= LIFT_TOL

    if lift_robust and rankings_stable:
        verdict = "PREDICTIONS_ROBUST_PROCEED_TO_STEP2"
    else:
        details = []
        if not lift_robust:
            details.append(f"lift swing |diff from original|={abs_diff_from_original:.4f} > {LIFT_TOL}")
        if not rankings_stable:
            details.append(f"rankings reshuffle: top3 intersect={top3_intersect}, bot3 intersect={bot3_intersect}")
        verdict = "RIDGE_ARTIFACT_SUSPECTED_PROCEED_TO_STEP2_REGARDLESS:" + "; ".join(details)

    # ---------------------------------------------------------------------------
    # Artifacts
    # ---------------------------------------------------------------------------
    output_dir = REPO_ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    findings = {
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "sport": SPORT,
        "regime": {
            "train_seasons": TRAIN_SEASONS,
            "holdout_seasons": HOLDOUT_SEASONS,
            "drop_seasons": DROP_SEASONS,
        },
        "ridge_values": RIDGE_VALUES,
        "original_lift": ORIGINAL_LIFT,
        "decision_criterion": {
            "lift_tol_from_original": LIFT_TOL,
            "lift_robust_threshold": "abs(lift - original_lift) <= lift_tol for ALL ridge values",
            "rankings_stable_threshold": "top-3 and bottom-3 intersect >= 2 between ridge_lo and ridge_hi",
        },
        "per_ridge": [
            {
                "ridge": r["ridge"],
                "baseline_accuracy": r["baseline_accuracy"],
                "ablation_accuracy": r["ablation_accuracy"],
                "accuracy_lift": r["accuracy_lift"],
                "beta_4_baseline": r["fit_baseline_coefficients"]["beta_4"],
                "fit_baseline_coefficients": r["fit_baseline_coefficients"],
            }
            for r in results
        ],
        "rankings_summary": summaries,
        "rank_correlation_lo_vs_hi": rank_pearson,
        "prediction_correlation_lo_vs_hi": pred_pearson,
        "prediction_max_abs_diff_lo_vs_hi": pred_max_abs_diff,
        "prediction_mean_abs_diff_lo_vs_hi": pred_mean_abs_diff,
        "lift_max_swing_across_ridge": max_lift_swing,
        "lift_max_abs_diff_from_original": abs_diff_from_original,
        "top3_intersect_size": top3_intersect,
        "bot3_intersect_size": bot3_intersect,
        "lift_robust": lift_robust,
        "rankings_stable": rankings_stable,
        "verdict": verdict,
    }
    (output_dir / "phase4d_step1_ridge_sensitivity.json").write_text(
        json.dumps(findings, indent=2, default=str)
    )

    # Markdown
    lines: list[str] = []
    lines.append("# Phase 4d Step 1 — Ridge Sensitivity (Girls Soccer)")
    lines.append("")
    lines.append(f"Generated: {findings['generated_utc']}")
    lines.append(f"Sport: {SPORT}")
    lines.append(f"Ridge values tested: {RIDGE_VALUES}")
    lines.append(f"Original Phase 4d acc lift (ridge=1e-6): {ORIGINAL_LIFT:+.4f}")
    lines.append("")
    lines.append("## Decision criterion (logged BEFORE the run)")
    lines.append("")
    lines.append(f"- **Robust**: acc lift within ±{LIFT_TOL} of original +{ORIGINAL_LIFT} across ALL three ridge values AND top-3 + bottom-3 rankings intersect ≥ 2 between lowest and highest ridge → predictions are robust, signal is 'real' predictively. Proceed to Step 2.")
    lines.append(f"- **Artifact suspected**: lift drops by >0.02 at higher ridge OR rankings reshuffle materially → document and proceed to Step 2 regardless (structural fix needed either way).")
    lines.append("")
    lines.append("## Per-ridge results")
    lines.append("")
    lines.append("| Ridge | Baseline acc | Ablation acc | Acc lift | β₄ | |lift - original| |")
    lines.append("|---:|---:|---:|---:|---:|---:|")
    for r in results:
        absdiff = abs(r["accuracy_lift"] - ORIGINAL_LIFT)
        lines.append(
            f"| {r['ridge']:.0e} | {r['baseline_accuracy']:.4f} | "
            f"{r['ablation_accuracy']:.4f} | "
            f"{r['accuracy_lift']:+.4f} | "
            f"{r['fit_baseline_coefficients']['beta_4']:+.4f} | "
            f"{absdiff:.4f} |"
        )
    lines.append("")
    lines.append(f"- max lift swing across ridge: {max_lift_swing:.4f}")
    lines.append(f"- max abs diff from original: {abs_diff_from_original:.4f}")
    lines.append(f"- lift robust ({'within' if lift_robust else 'OUTSIDE'} ±{LIFT_TOL}): **{lift_robust}**")
    lines.append("")
    lines.append("## Rankings at end-of-season (composite = offense - defense)")
    lines.append("")
    for ridge_str, summary in summaries.items():
        ridge_f = float(ridge_str)
        lines.append(f"### Ridge = {ridge_f:.0e}")
        lines.append("")
        lines.append("**Top-3:**")
        for t in summary["top_3"]:
            lines.append(f"- {t['name']} (id={t['team_id']}): composite = {t['composite']:+.3f}")
        lines.append("")
        lines.append("**Bottom-3:**")
        for t in summary["bottom_3"]:
            lines.append(f"- {t['name']} (id={t['team_id']}): composite = {t['composite']:+.3f}")
        lines.append("")
    lines.append("## Ranking stability")
    lines.append("")
    lines.append(f"- top-3 intersect (ridge=1e-6 vs ridge=1e-2): {top3_intersect} / 3")
    lines.append(f"- bottom-3 intersect (ridge=1e-6 vs ridge=1e-2): {bot3_intersect} / 3")
    lines.append(f"- Spearman rank correlation (ridge=1e-6 vs ridge=1e-2 over all common teams): {rank_pearson:.4f}" if rank_pearson is not None else "- rank correlation: n/a")
    lines.append(f"- rankings stable (top3 ∩ ≥ 2 AND bot3 ∩ ≥ 2): **{rankings_stable}**")
    lines.append("")
    lines.append("## Prediction correlation (holdout games)")
    lines.append("")
    if pred_pearson is not None:
        lines.append(f"- Pearson correlation of P(home_wins) between ridge=1e-6 and ridge=1e-2: {pred_pearson:.4f}")
        lines.append(f"- max abs prediction diff: {pred_max_abs_diff:.4f}")
        lines.append(f"- mean abs prediction diff: {pred_mean_abs_diff:.4f}")
    else:
        lines.append("- (no predictions computed)")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if verdict.startswith("PREDICTIONS_ROBUST"):
        lines.append("**PREDICTIONS ROBUST across ridge sweep.** Proceed to Step 2 (centering "
                     "constraints). Per Reese's instruction: the structural fix is needed either "
                     "way — robustness in predictions does NOT validate the off/def split as "
                     "well-defined ratings; the LS solve is operating in a 2+ degree-of-freedom "
                     "null-space and ridge is picking an arbitrary point.")
    else:
        lines.append("**RIDGE-ARTIFACT SUSPECTED.** Document the artifact. Proceed to Step 2 "
                     "regardless — the structural fix (Lagrange centering or explicit "
                     "reparameterization) is needed either way.")
        lines.append("")
        lines.append(f"Reasons: {verdict.split(':', 1)[-1].strip()}")
    lines.append("")
    lines.append("Halt after Step 1 per Reese 2026-05-27 sign-off sequencing. Do not start Step 2 without sign-off.")

    (output_dir / "phase4d_step1_ridge_sensitivity.md").write_text("\n".join(lines))

    # Console
    print()
    print("=" * 80)
    print(f"PHASE 4D STEP 1 RIDGE SENSITIVITY (Girls Soccer)")
    print("=" * 80)
    print(f"{'ridge':>10} {'b_acc':>8} {'a_acc':>8} {'lift':>8}  {'beta_4':>8}  {'|delta_orig|':>12}")
    for r in results:
        absdiff = abs(r['accuracy_lift'] - ORIGINAL_LIFT)
        print(
            f"{r['ridge']:>10.0e} {r['baseline_accuracy']:>8.4f} "
            f"{r['ablation_accuracy']:>8.4f} {r['accuracy_lift']:>+8.4f}  "
            f"{r['fit_baseline_coefficients']['beta_4']:>+8.4f}  {absdiff:>12.4f}"
        )
    print()
    print(f"top-3 intersect (lo vs hi): {top3_intersect} / 3")
    print(f"bot-3 intersect (lo vs hi): {bot3_intersect} / 3")
    if rank_pearson is not None:
        print(f"rank Spearman (lo vs hi):  {rank_pearson:+.4f}")
    if pred_pearson is not None:
        print(f"pred Pearson (lo vs hi):   {pred_pearson:+.4f}")
        print(f"pred max abs diff:         {pred_max_abs_diff:.4f}")
    print()
    print(f"VERDICT: {verdict}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
