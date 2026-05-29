"""Drift test: tier distribution across 100 random games.

Per Reese 2026-05-29 evening Spec 8 (REVISED for 4-tier UI):

  Pass criteria — 4-tier UI acceptance:
    - All 4 tiers fire at least once across 100 games (non-degenerate
      dispersion — confirms tier system is meaningful in practice)
    - Total of 4 tier counts equals total valid forecasts (accounting
      sanity check)
    - No single tier exceeds 90% of forecasts (catches catastrophic
      collapse to one label)

  Prior criteria (≥95% UI-shipped + ≤5% edge tiers) are obsolete and
  removed; that was the 2-tier-UI premise the drift test itself
  refuted (6.4% edge-tier fire rate empirically).

Run after each forecast methodology or tier-UI change to ensure tier
dispersion matches UX expectations.
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

    # Acceptance criteria — 4-tier UI (REVISED 2026-05-29 evening)
    print()
    print("=" * 80)
    pass_checks: list[str] = []
    fail_checks: list[str] = []

    # 1. All 4 tiers fire at least once — non-degenerate dispersion
    for tier in ("confident_pick", "lean", "toss_up", "long_shot"):
        c = tier_counter.get(tier, 0)
        if c > 0:
            pass_checks.append(f"{tier} fires: n={c}")
        else:
            fail_checks.append(f"{tier} never fires — tier collapse")

    # 2. Total accounting sanity — 4 tier counts should sum to n_with_forecast
    total_tier_count = sum(
        tier_counter.get(t, 0)
        for t in ("confident_pick", "lean", "toss_up", "long_shot")
    )
    if total_tier_count == n_with_forecast:
        pass_checks.append(
            f"tier accounting balanced: {total_tier_count} = {n_with_forecast}"
        )
    else:
        fail_checks.append(
            f"tier accounting imbalance: {total_tier_count} ≠ {n_with_forecast}"
        )

    # 3. No catastrophic collapse — no single tier > 90%
    for tier in ("confident_pick", "lean", "toss_up", "long_shot"):
        c = tier_counter.get(tier, 0)
        pct = (100 * c / n_with_forecast) if n_with_forecast else 0.0
        if pct > 90:
            fail_checks.append(
                f"{tier} collapse — {pct:.1f}% > 90% threshold"
            )
    pass_checks.append(
        f"no single tier > 90% (max: {max((100 * tier_counter.get(t, 0) / max(1, n_with_forecast)) for t in ('confident_pick', 'lean', 'toss_up', 'long_shot')):.1f}%)"
    )

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
