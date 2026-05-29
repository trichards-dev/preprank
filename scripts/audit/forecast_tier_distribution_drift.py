"""Drift test: tier distribution across 100 random games.

Per Reese 2026-05-29 evening (Option D approval, step 4): verify the
tier enum's actual distribution is non-degenerate, and that the 2-tier
UI (Confident pick / Lean) covers ~95%+ of predictions under current
holdout data. Toss-up and Long shot should be near-zero / zero — they're
defined in the API enum but reserved for edge cases (bins with very
thin n that don't exist in our current Phase 6 holdout).

Pass criteria:
  - ≥ 95% of sampled games land in confident_pick / lean
  - 0 ≤ Toss-up + Long shot proportion ≤ 5%
  - At least one game in each surfaced tier (confident_pick + lean) —
    confirms tier dispersion is happening, not all collapsed to one tier

Run after each forecast methodology change to ensure tier dispersion
matches the UX expectations.
"""
from __future__ import annotations

import json
import os
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / "apps" / "api" / ".env")

from fastapi.testclient import TestClient


SEED = 42
N_SAMPLES = 100


def main() -> int:
    from app.main import app
    client = TestClient(app)

    rng = random.Random(SEED)

    # Sample games across all 8 sports, weighted by approximate seeded n
    sports = ["Football", "Volleyball", "Boys Basketball", "Girls Basketball",
              "Baseball", "Softball", "Boys Soccer", "Girls Soccer"]
    samples_per_sport = N_SAMPLES // len(sports)  # ~12 per sport

    tier_counter: Counter[str] = Counter()
    sport_tier_counter: dict[str, Counter[str]] = {sp: Counter() for sp in sports}
    forecast_unavailable_count = 0
    total_sampled = 0

    for sport in sports:
        # Pull games for this sport
        resp = client.get(f"/api/v1/games/?season_year=2025&sport={sport}&limit=200")
        if resp.status_code != 200:
            continue
        games = resp.json()
        if not games:
            continue
        rng.shuffle(games)
        picked = games[:samples_per_sport]
        for g in picked:
            fc = client.get(f"/api/v1/games/{g['id']}/forecast")
            if fc.status_code != 200:
                continue
            body = fc.json()
            total_sampled += 1
            forecast = body.get("forecast")
            if forecast is None:
                forecast_unavailable_count += 1
                continue
            tier = forecast["confidence_tier"]
            tier_counter[tier] += 1
            sport_tier_counter[sport][tier] += 1

    n_with_forecast = total_sampled - forecast_unavailable_count

    print("=" * 80)
    print("TIER DISTRIBUTION DRIFT — 100-game sample (Option D binomial CI)")
    print("=" * 80)
    print(f"  Total sampled:        {total_sampled}")
    print(f"  Forecast unavailable: {forecast_unavailable_count}")
    print(f"  With valid forecast:  {n_with_forecast}")
    print()
    print(f"  Tier counts:")
    for tier in ("confident_pick", "lean", "toss_up", "long_shot"):
        c = tier_counter.get(tier, 0)
        pct = (100 * c / n_with_forecast) if n_with_forecast else 0.0
        marker = "  (UI-shipped)" if tier in ("confident_pick", "lean") else "  (API-only at v1.0)"
        print(f"    {tier:18s}  n={c:>3d}  {pct:5.1f}%{marker}")
    print()
    print("  Per-sport tier dispersion:")
    for sp in sports:
        counter = sport_tier_counter[sp]
        if not counter:
            print(f"    {sp:18s}  (no samples)")
            continue
        parts = []
        for tier in ("confident_pick", "lean", "toss_up", "long_shot"):
            if counter.get(tier, 0) > 0:
                parts.append(f"{tier}={counter[tier]}")
        print(f"    {sp:18s}  {'  '.join(parts)}")

    # Acceptance criteria
    print()
    print("=" * 80)
    pass_checks: list[str] = []
    fail_checks: list[str] = []

    # 1. >=95% in confident_pick + lean (the 2-tier UI surface)
    ui_tier_n = tier_counter.get("confident_pick", 0) + tier_counter.get("lean", 0)
    ui_tier_pct = (100 * ui_tier_n / n_with_forecast) if n_with_forecast else 0.0
    if ui_tier_pct >= 95:
        pass_checks.append(f"≥95% in 2-tier UI surface: {ui_tier_pct:.1f}%")
    else:
        fail_checks.append(f"<95% in 2-tier UI surface: {ui_tier_pct:.1f}%")

    # 2. Both surfaced tiers have at least one game
    if tier_counter.get("confident_pick", 0) > 0:
        pass_checks.append(f"confident_pick fires: n={tier_counter['confident_pick']}")
    else:
        fail_checks.append("confident_pick never fires — tier collapse")
    if tier_counter.get("lean", 0) > 0:
        pass_checks.append(f"lean fires: n={tier_counter['lean']}")
    else:
        fail_checks.append("lean never fires — tier collapse")

    # 3. Toss-up + Long shot proportion within 0-5% (acceptable edge-case range)
    edge_n = tier_counter.get("toss_up", 0) + tier_counter.get("long_shot", 0)
    edge_pct = (100 * edge_n / n_with_forecast) if n_with_forecast else 0.0
    if edge_pct <= 5:
        pass_checks.append(f"toss_up + long_shot ≤ 5%: {edge_pct:.1f}%")
    else:
        fail_checks.append(f"toss_up + long_shot > 5%: {edge_pct:.1f}% — review tier brackets")

    print(f"PASS CHECKS ({len(pass_checks)}):")
    for c in pass_checks:
        print(f"  ✓ {c}")
    if fail_checks:
        print()
        print(f"FAIL CHECKS ({len(fail_checks)}):")
        for c in fail_checks:
            print(f"  ✗ {c}")
    print()
    verdict = "PASS" if not fail_checks else "FAIL"
    print(f"DRIFT-TEST VERDICT: {verdict}")

    # Save artifact
    out = {
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "context": "Option D binomial CI tier-distribution drift test",
        "seed": SEED,
        "n_samples_target": N_SAMPLES,
        "n_total_sampled": total_sampled,
        "n_with_valid_forecast": n_with_forecast,
        "n_forecast_unavailable": forecast_unavailable_count,
        "tier_counts": dict(tier_counter),
        "tier_pct_of_valid": {
            t: (100 * tier_counter.get(t, 0) / n_with_forecast) if n_with_forecast else 0.0
            for t in ("confident_pick", "lean", "toss_up", "long_shot")
        },
        "per_sport_tier_counts": {sp: dict(c) for sp, c in sport_tier_counter.items()},
        "ui_tier_coverage_pct": ui_tier_pct,
        "edge_tier_pct": edge_pct,
        "passes": not fail_checks,
        "pass_checks": pass_checks,
        "fail_checks": fail_checks,
    }
    out_path = REPO_ROOT / "reports" / "audits" / "forecast_tier_distribution_drift.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[drift] artifacts → {out_path}")

    return 0 if not fail_checks else 1


if __name__ == "__main__":
    sys.exit(main())
