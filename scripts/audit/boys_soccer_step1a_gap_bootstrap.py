"""Step 1a diagnostic — Boys Soccer (train_acc - holdout_acc) bootstrap CI.

Reese 2026-05-27, after retracting the Boys Soccer "data drift" framing:

    "Sample-noise test: compare the +0.0281 against a paired bootstrap CI
     on (train_acc - holdout_acc). If CI straddles 0, the gap is noise
     and Boys Soccer needs no special handling."

Implementation note on "paired bootstrap" terminology
-----------------------------------------------------
Train and holdout are disjoint game sets (different seasons, different
counts). They cannot be paired game-by-game. The diagnostic Reese wants
is a CI on the *difference of accuracies* under sample-variation; the
standard tool for that is a two-sample independent bootstrap of the
difference:

    For b in 1..B:
        train_preds_b = sample-with-replacement(train_preds,
                                                size=len(train_preds))
        hold_preds_b  = sample-with-replacement(hold_preds,
                                                size=len(hold_preds))
        diff_b = acc(train_preds_b) - acc(hold_preds_b)
    CI_95 = 2.5th/97.5th percentile of {diff_b}

A CI straddling 0 means the observed +0.0281 gap is consistent with
pure resampling noise within the two pools, so the gap doesn't warrant
special handling.

Two fit variants are tested
---------------------------
The "+0.0281" gap Reese cited is the **Phase 2 baseline** number (no
recent-form feature). The Phase 4b reference model (recent-form
enabled) shows a much smaller gap because recent-form differentially
lifts holdout over train. Both variants are run so the diagnostic
unambiguously answers Reese's prompt and characterizes how the gap
moves with the feature stack.

Variant A — Phase 2 baseline (no recent-form): _build_training_rows()
            without recent_form_signals; same as run_phase2_baseline.
Variant B — Phase 4b reference (recent-form on): with
            precompute_team_week_form + β₆ free; same as the Phase 4b
            "fit_baseline" path.

Modified-(b) regime in both cases (drop 2021, train 2022-24, holdout 2025).

Output: reports/walk_forward/boys-soccer-step1a-gap-diagnostic/<ts>/
{ summary.json, report.md, predictions_phase2.jsonl, predictions_phase4b.jsonl }

The per-prediction records (with cold_start flags) are persisted so
Step 1b (cold-start vs non-cold-start gap split, conditional on Step 1a
CI excluding 0) can re-use them without refitting.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))

from dotenv import load_dotenv

import numpy as np

from engine.prediction.config import PredictionConfig
from engine.prediction.features.recent_form import precompute_team_week_form
from engine.validator.data import (
    RunInputs,
    load_run_inputs,
    load_sports_map,
    load_teams_with_schools,
)
from engine.validator.metrics import game_winner_accuracy
from engine.validator.runner_v2 import _build_training_rows, _predict_rows
from engine.prediction.model import GameTrainingRow, fit_sport


TRAIN_SEASONS = [2022, 2023, 2024]
HOLDOUT_SEASONS = [2025]
DROP_SEASONS = [2021]
SPORT = "Boys Soccer"


def _two_sample_diff_bootstrap(
    train_correct: np.ndarray,
    hold_correct: np.ndarray,
    *,
    n_resamples: int,
    seed: int,
) -> tuple[float, tuple[float, float], np.ndarray]:
    """Two-sample independent bootstrap of (train_acc - hold_acc).

    Returns (observed_diff, (lo95, hi95), all_diffs).
    """
    rng = np.random.default_rng(seed)
    n_t = len(train_correct)
    n_h = len(hold_correct)
    diffs = np.empty(n_resamples, dtype=np.float64)
    for i in range(n_resamples):
        t_idx = rng.integers(0, n_t, size=n_t)
        h_idx = rng.integers(0, n_h, size=n_h)
        t_acc = float(train_correct[t_idx].mean())
        h_acc = float(hold_correct[h_idx].mean())
        diffs[i] = t_acc - h_acc
    observed = float(train_correct.mean()) - float(hold_correct.mean())
    lo, hi = float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))
    return observed, (lo, hi), diffs


def _pred_to_jsonl_row(p) -> dict:
    """Persist enough to re-run Step 1b without refitting."""
    return {
        "sport": p.sport,
        "season_year": p.season_year,
        "week_number": p.week_number,
        "p_home": p.home_win_probability,
        "actual_home_won": p.actual_home_won,
        "home_cold_start": p.home_cold_start,
        "away_cold_start": p.away_cold_start,
        "home_rating_pregame": p.home_rating_pregame,
        "away_rating_pregame": p.away_rating_pregame,
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(
        prog="python scripts/audit/boys_soccer_step1a_gap_bootstrap.py",
        description="Step 1a: two-sample bootstrap CI on Boys Soccer (train_acc - hold_acc)",
    )
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output-root", default="reports/walk_forward")
    p.add_argument(
        "--config-label", default="boys-soccer-step1a-gap-diagnostic",
    )
    args = p.parse_args(argv)

    print(f"[step1a] sport={SPORT}")
    print(f"[step1a] regime: drop={DROP_SEASONS} train={TRAIN_SEASONS} holdout={HOLDOUT_SEASONS}")
    print(f"[step1a] n_bootstrap={args.n_bootstrap} seed={args.seed}")
    print()

    t0 = time.time()

    from engine.validator.runner import _default_supabase_client_factory
    sb = _default_supabase_client_factory()

    sports_map = load_sports_map(sb)
    name_to_id = {n.lower(): sid for sid, n in sports_map.items()}
    sid = name_to_id.get(SPORT.lower())
    if sid is None:
        print(f"[step1a] ERROR — sport {SPORT!r} not found in sports table")
        return 2

    teams = load_teams_with_schools(sb)
    rf_config = PredictionConfig()

    # Build BOTH training-row variants
    train_rows_p2: list[GameTrainingRow] = []
    hold_rows_p2: list[GameTrainingRow] = []
    train_rows_p4b: list[GameTrainingRow] = []
    hold_rows_p4b: list[GameTrainingRow] = []
    inputs_list: list[RunInputs] = []
    for season in TRAIN_SEASONS + HOLDOUT_SEASONS:
        if season in DROP_SEASONS:
            continue
        inp = load_run_inputs(sb, sid, SPORT, season, teams=teams)
        inputs_list.append(inp)
        # Phase 2 baseline: no recent_form_signals
        rows_p2 = _build_training_rows(inp)
        # Phase 4b reference: with recent_form_signals
        form_table = precompute_team_week_form(inp.games, SPORT, rf_config)
        rows_p4b = _build_training_rows(inp, recent_form_signals=form_table)
        if inp.season_year in HOLDOUT_SEASONS:
            hold_rows_p2.extend(rows_p2)
            hold_rows_p4b.extend(rows_p4b)
        else:
            train_rows_p2.extend(rows_p2)
            train_rows_p4b.extend(rows_p4b)

    if not train_rows_p2 or not hold_rows_p2:
        print(f"[step1a] ERROR — insufficient rows: train={len(train_rows_p2)} hold={len(hold_rows_p2)}")
        return 2

    print(f"[step1a] n_train_rows={len(train_rows_p2)}  n_hold_rows={len(hold_rows_p2)}")

    def _run_variant(label: str, train_rows, hold_rows):
        print()
        print(f"--- Variant {label} ---")
        fit = fit_sport(SPORT, train_rows, cv_seed=args.seed)
        print(f"[step1a {label}] fit converged={fit.converged} loss={fit.loss:.4f} λ/game={fit.selected_lambda_per_game:.6f}")
        print(f"[step1a {label}] coefficients: " + " ".join(f"{k}={v:+.4f}" for k, v in fit.coefficients.items()))

        config = PredictionConfig(model_coefficients_by_sport={SPORT: fit.coefficients})
        train_preds = _predict_rows(train_rows, SPORT, config)
        hold_preds = _predict_rows(hold_rows, SPORT, config)

        train_acc = game_winner_accuracy(train_preds)
        hold_acc = game_winner_accuracy(hold_preds)
        observed_gap = train_acc - hold_acc

        train_correct = np.array(
            [1.0 if (p.home_win_probability >= 0.5) == p.actual_home_won else 0.0
             for p in train_preds],
            dtype=np.float64,
        )
        hold_correct = np.array(
            [1.0 if (p.home_win_probability >= 0.5) == p.actual_home_won else 0.0
             for p in hold_preds],
            dtype=np.float64,
        )

        obs_diff, (ci_lo, ci_hi), all_diffs = _two_sample_diff_bootstrap(
            train_correct, hold_correct,
            n_resamples=args.n_bootstrap, seed=args.seed,
        )
        assert abs(obs_diff - observed_gap) < 1e-9, (obs_diff, observed_gap)

        ci_straddles_zero = (ci_lo <= 0.0 <= ci_hi)
        if obs_diff >= 0:
            p_two_sided = 2.0 * float((all_diffs <= 0).mean())
        else:
            p_two_sided = 2.0 * float((all_diffs >= 0).mean())
        p_two_sided = min(p_two_sided, 1.0)

        return {
            "fit": fit,
            "train_preds": train_preds,
            "hold_preds": hold_preds,
            "train_accuracy": train_acc,
            "holdout_accuracy": hold_acc,
            "observed_gap": observed_gap,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
            "ci_straddles_zero": ci_straddles_zero,
            "p_two_sided": p_two_sided,
            "all_diffs_mean": float(all_diffs.mean()),
            "all_diffs_std": float(all_diffs.std(ddof=1)),
        }

    v_p2 = _run_variant("phase2_baseline_no_recent_form", train_rows_p2, hold_rows_p2)
    v_p4b = _run_variant("phase4b_reference_with_recent_form", train_rows_p4b, hold_rows_p4b)

    # The verdict that gates Step 1b is the Phase 2 baseline gap (the +0.0281 number)
    primary = v_p2

    elapsed = time.time() - t0

    # ----- write artifacts -----
    now = datetime.utcnow()
    out_root = Path(args.output_root)
    run_dir = out_root / args.config_label / now.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)

    def _variant_summary(v: dict) -> dict:
        return {
            "fit": {
                "converged": v["fit"].converged,
                "loss": v["fit"].loss,
                "selected_lambda_per_game": v["fit"].selected_lambda_per_game,
                "coefficients": dict(v["fit"].coefficients),
            },
            "observed": {
                "train_accuracy": v["train_accuracy"],
                "holdout_accuracy": v["holdout_accuracy"],
                "gap_train_minus_holdout": v["observed_gap"],
            },
            "bootstrap": {
                "n_resamples": args.n_bootstrap,
                "seed": args.seed,
                "ci_95": [v["ci_lo"], v["ci_hi"]],
                "ci_straddles_zero": v["ci_straddles_zero"],
                "p_two_sided_vs_zero": v["p_two_sided"],
                "all_diffs_mean": v["all_diffs_mean"],
                "all_diffs_std": v["all_diffs_std"],
            },
        }

    summary = {
        "diagnostic": "Step 1a — Boys Soccer (train_acc - hold_acc) two-sample bootstrap",
        "regime": {
            "drop_seasons": DROP_SEASONS,
            "train_seasons": TRAIN_SEASONS,
            "holdout_seasons": HOLDOUT_SEASONS,
        },
        "sport": SPORT,
        "timestamp_utc": now.isoformat(),
        "n_train_rows": len(train_rows_p2),
        "n_hold_rows": len(hold_rows_p2),
        "primary_variant": "phase2_baseline_no_recent_form",
        "primary_rationale": "the '+0.0281' gap Reese cited is the Phase 2 baseline gap (no recent-form feature)",
        "variants": {
            "phase2_baseline_no_recent_form": _variant_summary(v_p2),
            "phase4b_reference_with_recent_form": _variant_summary(v_p4b),
        },
        "wall_time_sec": elapsed,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # Persist predictions for Step 1b reuse — one file per variant
    for label, v, fname in (
        ("phase2", v_p2, "predictions_phase2.jsonl"),
        ("phase4b", v_p4b, "predictions_phase4b.jsonl"),
    ):
        with (run_dir / fname).open("w") as f:
            for rec in v["train_preds"]:
                row = _pred_to_jsonl_row(rec)
                row["fold"] = "train"
                f.write(json.dumps(row) + "\n")
            for rec in v["hold_preds"]:
                row = _pred_to_jsonl_row(rec)
                row["fold"] = "holdout"
                f.write(json.dumps(row) + "\n")

    # Markdown report
    lines: list[str] = []
    lines.append("# Step 1a — Boys Soccer (train_acc - holdout_acc) Bootstrap CI")
    lines.append("")
    lines.append(f"Run timestamp (UTC): {now.isoformat()}")
    lines.append(f"Wall-clock: {elapsed/60:.2f} min")
    lines.append("")
    lines.append("## Regime")
    lines.append("")
    lines.append(f"- Drop seasons: {DROP_SEASONS}")
    lines.append(f"- Train seasons: {TRAIN_SEASONS}")
    lines.append(f"- Holdout seasons: {HOLDOUT_SEASONS}")
    lines.append(f"- Sport: {SPORT}")
    lines.append("")
    lines.append("## Sample sizes")
    lines.append("")
    lines.append(f"- n_train_rows = {len(train_rows_p2)}")
    lines.append(f"- n_hold_rows  = {len(hold_rows_p2)}")
    lines.append("")
    lines.append("## Two-variant bootstrap")
    lines.append("")
    lines.append(
        "The '+0.0281' gap Reese cited 2026-05-27 is the **Phase 2 baseline** number "
        "(no recent-form feature). This is the primary diagnostic. The Phase 4b "
        "reference variant (recent-form enabled, beta_6 free) is also reported because "
        "it's the model that actually advances through Phase 4 and because the gap "
        "depends materially on which features the fit reads."
    )
    lines.append("")
    lines.append("| Variant | train_acc | hold_acc | gap | 95% CI on gap | straddles 0 | p (two-sided) |")
    lines.append("|---|---:|---:|---:|---:|:---:|---:|")
    for label, v in (
        ("Phase 2 (no recent-form) — PRIMARY", v_p2),
        ("Phase 4b reference (recent-form on)", v_p4b),
    ):
        lines.append(
            f"| {label} | {v['train_accuracy']:.4f} | {v['holdout_accuracy']:.4f} | "
            f"{v['observed_gap']:+.4f} | "
            f"[{v['ci_lo']:+.4f}, {v['ci_hi']:+.4f}] | "
            f"{'YES' if v['ci_straddles_zero'] else 'no'} | "
            f"{v['p_two_sided']:.4f} |"
        )
    lines.append("")
    lines.append("## Fit details")
    lines.append("")
    for label, v in (("Phase 2 baseline", v_p2), ("Phase 4b reference", v_p4b)):
        lines.append(f"### {label}")
        lines.append("")
        lines.append(f"- converged: {v['fit'].converged}")
        lines.append(f"- loss: {v['fit'].loss:.4f}")
        lines.append(f"- λ/game: {v['fit'].selected_lambda_per_game:.6f}")
        coef_str = "  ".join(f"{k}={cv:+.4f}" for k, cv in v["fit"].coefficients.items())
        lines.append(f"- coefficients: {coef_str}")
        lines.append("")
    lines.append("## Verdict")
    lines.append("")
    p2_straddles = v_p2["ci_straddles_zero"]
    p4_straddles = v_p4b["ci_straddles_zero"]
    if p2_straddles and p4_straddles:
        lines.append(
            "**Both variants' CIs straddle 0.** The +0.0281 Phase 2 baseline gap and "
            "the +0.0054 Phase 4b reference gap are both consistent with pure "
            "resampling noise within the train and holdout pools. By Reese's "
            "2026-05-27 Step 1 branching rule, Boys Soccer **needs no special "
            "handling**. Step 1b (cold-start vs non-cold-start split) is NOT "
            "triggered. Phase 4c may proceed once Reese sign-off lands."
        )
    elif p2_straddles and not p4_straddles:
        lines.append(
            "**Primary (Phase 2) CI straddles 0; Phase 4b CI excludes 0.** The "
            "originally-cited +0.0281 gap appears to be sample noise, but the "
            "recent-form-enabled model shows a real (non-zero) gap. Recommend "
            "running Step 1b on the **Phase 4b variant** to characterize that "
            "smaller-but-real gap before Phase 4c."
        )
    elif not p2_straddles and p4_straddles:
        lines.append(
            "**Primary (Phase 2) CI excludes 0; Phase 4b CI straddles 0.** The "
            "+0.0281 gap is real for the bare-bones baseline, but the recent-form "
            "feature has effectively closed it. Phase 4c can proceed without Step 1b "
            "on the Phase 4b model. If a Phase 2 model is ever shipped without "
            "recent-form, Step 1b should run first."
        )
    else:
        lines.append(
            "**Both variants' CIs exclude 0.** The gap is real in both fit "
            "configurations. By Reese's 2026-05-27 Step 1 branching rule, **Step 1b "
            "is triggered** on both variants: cold-start vs non-cold-start gap split "
            "on the Boys Soccer holdout."
        )
    lines.append("")
    lines.append("## Notes on method")
    lines.append("")
    lines.append(
        "Train and holdout are disjoint game sets (different seasons), so a strict "
        "paired bootstrap is undefined. The standard tool for a CI on the "
        "*difference of two-sample proportions* is the two-sample independent "
        "bootstrap used here: each resample draws-with-replacement from train and "
        "from holdout independently, computes accuracies on the resampled pools, "
        "and stores the difference. Mirror image of the Phase 4b paired-bootstrap, "
        "but adapted to the two-sample (cross-pool) case."
    )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- summary.json")
    lines.append(f"- predictions_phase2.jsonl (train+holdout, with cold_start flags; reusable for Step 1b)")
    lines.append(f"- predictions_phase4b.jsonl (train+holdout, with cold_start flags; reusable for Step 1b)")
    lines.append("")
    lines.append("External-release status: INTERNAL only. No external numbers leave the office "
                 "pre-candidate-final per decisions.md TASK 3 output discipline.")

    (run_dir / "report.md").write_text("\n".join(lines))

    # ----- console summary -----
    print()
    print("=" * 70)
    print(f"{'variant':40} {'gap':>8}  {'95% CI':>22}  straddle0  p")
    for label, v in (
        ("Phase 2 baseline (no recent-form)*PRIMARY", v_p2),
        ("Phase 4b reference (recent-form on)      ", v_p4b),
    ):
        print(
            f"{label:40} {v['observed_gap']:+.4f}  "
            f"[{v['ci_lo']:+.4f}, {v['ci_hi']:+.4f}]  "
            f"{'YES' if v['ci_straddles_zero'] else 'no ':>9}  "
            f"{v['p_two_sided']:.4f}"
        )
    print()
    print(f"[step1a] artifacts -> {run_dir}")
    print(f"[step1a] wall-clock: {elapsed/60:.2f} min")
    print()
    p2_straddles = v_p2["ci_straddles_zero"]
    p4_straddles = v_p4b["ci_straddles_zero"]
    if p2_straddles and p4_straddles:
        print("VERDICT: both variants' CIs straddle 0. Step 1b NOT triggered.")
    elif p2_straddles and not p4_straddles:
        print("VERDICT: primary (Phase 2) CI straddles 0 but Phase 4b excludes 0. Step 1b recommended on Phase 4b variant.")
    elif not p2_straddles and p4_straddles:
        print("VERDICT: primary (Phase 2) CI excludes 0 but Phase 4b straddles 0. Recent-form closes the gap; Step 1b not needed for Phase 4c.")
    else:
        print("VERDICT: both CIs exclude 0. Step 1b triggered (cold-start split).")
    print()
    print("Halting after Step 1a per Reese 2026-05-27 sequencing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
