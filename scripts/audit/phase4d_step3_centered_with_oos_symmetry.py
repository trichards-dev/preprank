"""Phase 4d Step 3 — centered Massey re-run + 3-config OOS-symmetry test.

Reese 2026-05-27 evening:
  - Re-run Phase 4d ablation on all 8 sports with the CENTERED Massey
    implementation (1c9da4e). Standard discipline.
  - 3-config OOS-symmetry test layered on:
      (i)  Massey filters OOS + recent_form filters OOS (symmetric clean)
      (ii) Massey filters OOS + recent_form does NOT (current — Phase 4d
           original config)
      (iii) Neither filters OOS (symmetric dirty)
  - Compare per-sport lift across all three configs side-by-side with
    the ORIGINAL Phase 4d numbers (uncentered, config ii).
  - HALT after results. DO NOT proceed to audits (held pending B).

Implementation notes
--------------------
- Beta_3 is pinned to 0 throughout (Phase 4c disposition).
- Reference fit: beta_3 pinned, beta_4 free, beta_6 free.
- Ablation fit: beta_3 AND beta_4 pinned, beta_6 free.
- The "OOS filtering" is applied at the GAME-LIST layer per config:
    - For "recent_form filters OOS": pre-filter games list to in-state
      before passing to precompute_team_week_form.
    - For "Massey does NOT filter OOS" (config iii): force
      is_out_of_state=False on every game copy passed to
      precompute_team_week_massey_od (bypasses internal filter).
- Standard 1000-resample paired bootstrap CI per (sport, config),
  BH-FDR across sports within each config.
- Modified-(b) regime (drop 2021, train 22-24, validate 25).

Output: reports/walk_forward/wf-phase4d-step3-centered-oos-sweep/<ts>/
{summary.json, report.md}
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

from engine.prediction.config import PredictionConfig
from engine.prediction.features.log_margin import precompute_team_week_log_margins
from engine.prediction.features.massey_od import (
    MasseyConditioningError,
    precompute_team_week_massey_od,
)
from engine.prediction.features.recent_form import precompute_team_week_form
from engine.prediction.model import fit_sport
from engine.validator.data import (
    ALL_SPORTS,
    RunInputs,
    load_run_inputs,
    load_sports_map,
    load_teams_with_schools,
)
from engine.validator.fdr import benjamini_hochberg
from engine.validator.metrics import brier_score, game_winner_accuracy
from engine.validator.runner_v2 import (
    PHASE4_PINNED_INDICES,
    _build_training_rows,
    _paired_bootstrap_lift,
    _predict_rows,
)


TRAIN_SEASONS = [2022, 2023, 2024]
HOLDOUT_SEASONS = [2025]
DROP_SEASONS = [2021]

CONFIGS = ["i_symmetric_clean", "ii_asymmetric_current", "iii_symmetric_dirty"]


# Reese-provided original Phase 4d numbers (uncentered, config ii)
ORIGINAL_PHASE_4D = {
    "Girls Soccer": +0.1105,
    "Boys Soccer": +0.0649,
    "Volleyball": +0.0626,
    "Girls Basketball": +0.0586,
    "Softball": +0.0543,
    "Boys Basketball": +0.0427,
    "Football": +0.0417,
    "Baseball": +0.0323,
}


def make_supabase():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def _games_for_recent_form(games: list[dict], filter_oos: bool) -> list[dict]:
    """Pre-filter games before passing to recent_form precompute.
    recent_form does NOT filter OOS internally; pre-filtering at this
    layer is how we control its OOS behavior per config."""
    if filter_oos:
        return [g for g in games if not g.get("is_out_of_state")]
    return list(games)


def _games_for_massey(games: list[dict], filter_oos: bool) -> list[dict]:
    """Pre-process games before passing to massey_od precompute.
    massey_od DOES filter OOS internally (in _extract_game_sides). To
    DISABLE that filter for config iii, we force is_out_of_state=False
    on a shallow copy of each game dict."""
    if filter_oos:
        return list(games)   # internal filter handles OOS removal
    # force is_out_of_state=False to bypass internal filter
    return [{**g, "is_out_of_state": False} for g in games]


def run_one_config(
    config_name: str,
    massey_filter_oos: bool,
    form_filter_oos: bool,
    sport_id_map: dict[str, int],
    teams: dict,
    sb,
    sports: list[str],
    n_bootstrap: int,
    seed: int,
    fdr_alpha: float,
) -> dict:
    """Run one of the three OOS-symmetry configs across all sports.

    Returns dict with per-sport results, FDR flags, and metadata.
    """
    print(f"\n[step3] === config {config_name} "
          f"(massey_filter_oos={massey_filter_oos}, form_filter_oos={form_filter_oos}) ===")
    rf_config = PredictionConfig()
    per_sport = {}
    per_sport_p_values = []

    for sport in sports:
        sid = sport_id_map.get(sport)
        if sid is None:
            continue

        inputs_list: list[RunInputs] = []
        for season in TRAIN_SEASONS + HOLDOUT_SEASONS:
            if season in DROP_SEASONS:
                continue
            inputs_list.append(load_run_inputs(sb, sid, sport, season, teams=teams))

        train_rows = []
        hold_rows = []
        for inp in inputs_list:
            games_form = _games_for_recent_form(inp.games, form_filter_oos)
            games_massey = _games_for_massey(inp.games, massey_filter_oos)
            form_table = precompute_team_week_form(games_form, sport, rf_config)
            log_margin_table = precompute_team_week_log_margins(inp.games)
            try:
                massey_table = precompute_team_week_massey_od(games_massey)
            except MasseyConditioningError as e:
                print(f"  {sport}: massey conditioning failed at all weeks — {e}")
                massey_table = {}
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

        if not train_rows or not hold_rows:
            print(f"  {sport}: insufficient rows — skipped")
            continue

        # Reference: β₃ pinned, β₄ free
        fit_b = fit_sport(sport, train_rows, cv_seed=seed,
                          fixed_indices=list(PHASE4_PINNED_INDICES))
        # Ablation: β₃ AND β₄ pinned
        fit_a = fit_sport(sport, train_rows, cv_seed=seed,
                          fixed_indices=list(PHASE4_PINNED_INDICES) + [4])

        config_b = PredictionConfig(model_coefficients_by_sport={sport: fit_b.coefficients})
        config_a = PredictionConfig(model_coefficients_by_sport={sport: fit_a.coefficients})
        preds_b = _predict_rows(hold_rows, sport, config_b)
        preds_a = _predict_rows(hold_rows, sport, config_a)

        b_acc = game_winner_accuracy(preds_b)
        a_acc = game_winner_accuracy(preds_a)
        b_bri = brier_score(preds_b)
        a_bri = brier_score(preds_a)

        acc_lift, acc_ci, brier_lift, brier_ci, p_one = _paired_bootstrap_lift(
            preds_b, preds_a, n_resamples=n_bootstrap, seed=seed,
        )

        per_sport[sport] = {
            "n_holdout": len(hold_rows),
            "baseline_accuracy": b_acc,
            "ablation_accuracy": a_acc,
            "accuracy_lift": acc_lift,
            "accuracy_lift_ci": list(acc_ci),
            "brier_lift": brier_lift,
            "brier_lift_ci": list(brier_ci),
            "p_value_one_sided": p_one,
            "beta_4": fit_b.coefficients.get("beta_4", 0.0),
            "beta_6": fit_b.coefficients.get("beta_6", 0.0),
        }
        per_sport_p_values.append((sport, p_one))
        print(f"  {sport:18}  β₄={fit_b.coefficients.get('beta_4', 0.0):+.4f}  "
              f"acc_lift={acc_lift:+.4f}  [{acc_ci[0]:+.4f}, {acc_ci[1]:+.4f}]  "
              f"p={p_one:.4f}")

    # BH-FDR within this config
    n_significant_after_fdr = 0
    if per_sport_p_values:
        sport_names = [s for s, _ in per_sport_p_values]
        p_list = [p for _, p in per_sport_p_values]
        flags = benjamini_hochberg(p_list, alpha=fdr_alpha)
        for sport, sig in zip(sport_names, flags):
            sr = per_sport[sport]
            sr["significant_after_fdr"] = bool(sig and sr["accuracy_lift_ci"][0] > 0.0)
            if sr["significant_after_fdr"]:
                n_significant_after_fdr += 1
    for sport, sr in per_sport.items():
        sr.setdefault("significant_after_fdr", False)

    return {
        "config": config_name,
        "massey_filter_oos": massey_filter_oos,
        "form_filter_oos": form_filter_oos,
        "n_significant_after_fdr": n_significant_after_fdr,
        "per_sport": per_sport,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-root", default="reports/walk_forward")
    p.add_argument("--config-label", default="wf-phase4d-step3-centered-oos-sweep")
    p.add_argument("--n-bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--fdr-alpha", type=float, default=0.05)
    p.add_argument("--audit-threshold", type=float, default=0.02)
    p.add_argument("--sports", default=None)
    args = p.parse_args()

    sports = args.sports.split(",") if args.sports else list(ALL_SPORTS)
    print(f"[step3] config_label={args.config_label}")
    print(f"[step3] train={TRAIN_SEASONS} holdout={HOLDOUT_SEASONS} drop={DROP_SEASONS}")
    print(f"[step3] sports={sports}")
    print(f"[step3] β₃ pinned (Phase 4c disposition); β₄ ablation; β₆ free")
    print(f"[step3] Massey: CENTERED reparameterization (commit 1c9da4e), cond<1e4 guardrail")

    sb = make_supabase()
    sport_id_map = {row["name"]: row["id"] for row in sb.table("sports").select("id, name").execute().data}
    teams = load_teams_with_schools(sb)

    t0 = time.time()
    results = []
    config_specs = [
        ("i_symmetric_clean",    True,  True),
        ("ii_asymmetric_current", True, False),
        ("iii_symmetric_dirty",  False, False),
    ]
    for config_name, massey_oos, form_oos in config_specs:
        r = run_one_config(
            config_name=config_name,
            massey_filter_oos=massey_oos,
            form_filter_oos=form_oos,
            sport_id_map=sport_id_map, teams=teams, sb=sb, sports=sports,
            n_bootstrap=args.n_bootstrap, seed=args.seed, fdr_alpha=args.fdr_alpha,
        )
        results.append(r)
    elapsed = time.time() - t0

    # Output artifacts
    now = datetime.utcnow()
    run_dir = REPO_ROOT / args.output_root / args.config_label / now.strftime("%Y-%m-%d-%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)

    findings = {
        "generated_utc": now.isoformat() + "Z",
        "regime": {"train_seasons": TRAIN_SEASONS, "holdout_seasons": HOLDOUT_SEASONS, "drop_seasons": DROP_SEASONS},
        "config_label": args.config_label,
        "n_bootstrap": args.n_bootstrap,
        "seed": args.seed,
        "fdr_alpha": args.fdr_alpha,
        "audit_threshold": args.audit_threshold,
        "original_phase_4d_lifts": ORIGINAL_PHASE_4D,
        "configs": results,
        "wall_time_sec": elapsed,
    }
    (run_dir / "summary.json").write_text(json.dumps(findings, indent=2, default=str))

    # Markdown report
    sports_in_order = [
        "Football", "Volleyball", "Boys Basketball", "Girls Basketball",
        "Boys Soccer", "Girls Soccer", "Baseball", "Softball",
    ]
    lines = []
    lines.append("# Phase 4d Step 3 — Centered Massey re-run + 3-config OOS-symmetry test")
    lines.append("")
    lines.append(f"Run timestamp (UTC): {now.isoformat()}")
    lines.append(f"Wall-clock: {elapsed/60:.1f} min")
    lines.append(f"Massey: centered reparameterization (commit 1c9da4e), cond<1e4 guardrail")
    lines.append(f"β₃ pinned (Phase 4c disposition); β₄ ablation; β₆ free")
    lines.append("")
    lines.append("## Per-sport accuracy lift across 3 configs vs original Phase 4d")
    lines.append("")
    lines.append("| Sport | Original (uncentered, ii) | (i) symmetric clean | (ii) current asym | (iii) symmetric dirty |")
    lines.append("|---|---:|---:|---:|---:|")
    by_config = {r["config"]: r for r in results}
    for sport in sports_in_order:
        orig = ORIGINAL_PHASE_4D.get(sport, float("nan"))
        cells = [f"+{orig:.4f}"]
        for cname in ["i_symmetric_clean", "ii_asymmetric_current", "iii_symmetric_dirty"]:
            sr = by_config[cname]["per_sport"].get(sport)
            if sr is None:
                cells.append("n/a")
            else:
                fdr = "*" if sr.get("significant_after_fdr") else ""
                lift = sr["accuracy_lift"]
                cells.append(f"{lift:+.4f}{fdr}")
        lines.append(f"| {sport} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("Asterisk (*) = FDR-significant within its config (BH α=0.05) AND CI lower bound > 0.")
    lines.append("")
    lines.append("## Per-sport detail by config")
    lines.append("")
    for cname in ["i_symmetric_clean", "ii_asymmetric_current", "iii_symmetric_dirty"]:
        r = by_config[cname]
        lines.append(f"### Config {cname}  (massey_filter_oos={r['massey_filter_oos']}, form_filter_oos={r['form_filter_oos']})")
        lines.append("")
        lines.append(f"FDR-significant sports: {r['n_significant_after_fdr']} / {len(r['per_sport'])}")
        lines.append("")
        lines.append("| Sport | β₄ | β₆ | Ref acc | Abl acc | Acc lift | 95% CI | p | FDR | >2pp |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|")
        for sport in sports_in_order:
            sr = r["per_sport"].get(sport)
            if sr is None:
                continue
            fdr = "YES" if sr["significant_after_fdr"] else "no"
            audit = "AUDIT" if sr["accuracy_lift"] > args.audit_threshold else ""
            lines.append(
                f"| {sport} | {sr['beta_4']:+.4f} | {sr['beta_6']:+.4f} | "
                f"{sr['baseline_accuracy']:.4f} | {sr['ablation_accuracy']:.4f} | "
                f"{sr['accuracy_lift']:+.4f} | "
                f"[{sr['accuracy_lift_ci'][0]:+.4f}, {sr['accuracy_lift_ci'][1]:+.4f}] | "
                f"{sr['p_value_one_sided']:.4f} | {fdr} | {audit} |"
            )
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Per Reese 2026-05-27: audits HELD pending Workstream B universe expansion. ")
    lines.append("DO NOT proceed to per-sport replay audits on the current under-coverage universe.")

    (run_dir / "report.md").write_text("\n".join(lines))

    # ---------------- console summary ----------------
    print()
    print("=" * 110)
    print("Per-sport lifts across configs (vs original Phase 4d uncentered):")
    print()
    print(f"{'Sport':<18}  {'Original':>9}  {'(i) clean':>10}  {'(ii) current':>13}  {'(iii) dirty':>12}")
    for sport in sports_in_order:
        orig = ORIGINAL_PHASE_4D.get(sport, float("nan"))
        row_str = f"{sport:<18}  {orig:>+9.4f}"
        for cname in ["i_symmetric_clean", "ii_asymmetric_current", "iii_symmetric_dirty"]:
            sr = by_config[cname]["per_sport"].get(sport)
            if sr is None:
                row_str += "  " + "n/a".rjust(12)
            else:
                fdr = "*" if sr.get("significant_after_fdr") else " "
                row_str += f"  {sr['accuracy_lift']:>+12.4f}{fdr}"
        print(row_str)
    print()
    for cname in ["i_symmetric_clean", "ii_asymmetric_current", "iii_symmetric_dirty"]:
        r = by_config[cname]
        n_audit = sum(1 for sr in r["per_sport"].values() if sr["accuracy_lift"] > args.audit_threshold)
        print(f"  config {cname}: FDR-sig {r['n_significant_after_fdr']}/{len(r['per_sport'])},  audit-threshold-tripped {n_audit}/{len(r['per_sport'])}")
    print()
    print(f"Artifacts: {run_dir.relative_to(REPO_ROOT)}/")
    print(f"Wall-clock: {elapsed/60:.1f} min")
    print()
    print("Audits HELD pending Workstream B per Reese 2026-05-27.")
    print("Halting after Step 3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
