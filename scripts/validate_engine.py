"""Validate the power rating engine against LHSAA published ratings.

Takes a game results CSV, runs it through the ingestion pipeline and the
power rating engine, then compares computed ratings against the published
LHSAA final ratings from the seed CSV.

Usage:
    python -m scripts.validate_engine data/game_results/2025_football_game_results.csv

Reports:
- Per-team comparison: computed vs published rating and strength factor
- Discrepancies > 0.05 flagged
- Per-game breakdown for flagged teams
- Aggregate accuracy metrics (MAE, max error, correlation)
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from engine.power_rating import calculate_all_ratings
from scripts.ingest_game_results import ingest, SEED_CSV


def load_published_ratings() -> dict[str, dict]:
    """Load published LHSAA ratings from seed CSV, keyed by school name."""
    published = {}
    with open(SEED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            published[row["school"].strip()] = {
                "power_rating": float(row["power_rating"]),
                "strength_factor": float(row["strength_factor"]),
                "wins": int(row["wins"]),
                "losses": int(row["losses"]),
                "division": row["division"],
                "select_status": row["select_status"],
                "rank": int(row["rank"]),
            }
    return published


def validate(csv_path: Path):
    # Ingest game results
    data = ingest(csv_path)
    published = load_published_ratings()

    print(f"Ingested {sum(len(g) for g in data.games.values()) // 2} unique games, "
          f"{len(data.records)} teams")
    print()

    # Show ingestion warnings
    if data.warnings:
        print(f"INGESTION WARNINGS ({len(data.warnings)}):")
        for w in data.warnings:
            print(f"  - {w}")
        print()

    # Run the engine
    results = calculate_all_ratings(data.records, list(data.games.values()) if isinstance(data.games, dict) else data.games)

    # Compare against published ratings for teams that appear in both
    THRESHOLD = 0.05

    comparisons = []
    for name, pub in published.items():
        if name not in data.name_to_id:
            continue

        tid = data.name_to_id[name]
        computed = results[tid]
        rec = data.records[tid]

        rating_diff = computed.power_rating - pub["power_rating"]
        sf_diff = computed.strength_factor - pub["strength_factor"]

        comparisons.append({
            "name": name,
            "division": pub["division"],
            "select_status": pub["select_status"],
            "published_rank": pub["rank"],
            "record_match": rec.wins == pub["wins"] and rec.losses == pub["losses"],
            "computed_record": f"{rec.wins}-{rec.losses}",
            "published_record": f"{pub['wins']}-{pub['losses']}",
            "computed_rating": computed.power_rating,
            "published_rating": pub["power_rating"],
            "rating_diff": rating_diff,
            "computed_sf": computed.strength_factor,
            "published_sf": pub["strength_factor"],
            "sf_diff": sf_diff,
            "game_details": computed.game_details,
            "tid": tid,
        })

    comparisons.sort(key=lambda c: c["published_rank"])

    # Summary table
    print("=" * 110)
    print("POWER RATING COMPARISON: Computed vs Published")
    print("=" * 110)
    print(f"{'#':>3} {'School':<35} {'Rec':>5} {'Computed':>9} {'Published':>10} "
          f"{'Diff':>7} {'SF Comp':>8} {'SF Pub':>7} {'SF Diff':>8} {'Status':>8}")
    print("-" * 110)

    flagged = []
    all_diffs = []
    all_sf_diffs = []

    for c in comparisons:
        diff_str = f"{c['rating_diff']:+.2f}"
        sf_diff_str = f"{c['sf_diff']:+.2f}"
        status = "OK" if abs(c["rating_diff"]) <= THRESHOLD else "FLAGGED"
        if not c["record_match"]:
            status = "REC_ERR"

        if abs(c["rating_diff"]) > THRESHOLD or not c["record_match"]:
            flagged.append(c)

        all_diffs.append(c["rating_diff"])
        all_sf_diffs.append(c["sf_diff"])

        marker = ">>>" if status != "OK" else "   "
        print(f"{marker}{c['published_rank']:>3} {c['name']:<35} {c['computed_record']:>5} "
              f"{c['computed_rating']:>9.2f} {c['published_rating']:>10.2f} "
              f"{diff_str:>7} {c['computed_sf']:>8.2f} {c['published_sf']:>7.2f} "
              f"{sf_diff_str:>8} {status:>8}")

    # Per-game breakdown for flagged teams
    if flagged:
        print(f"\n{'=' * 110}")
        print(f"FLAGGED TEAMS — PER-GAME BREAKDOWN ({len(flagged)} teams)")
        print(f"{'=' * 110}")

        for c in flagged:
            print(f"\n--- {c['name']} (Div {c['division']} {c['select_status']}) ---")
            print(f"    Record: {c['computed_record']} "
                  f"(published: {c['published_record']})")
            print(f"    Computed: {c['computed_rating']:.2f}  "
                  f"Published: {c['published_rating']:.2f}  "
                  f"Diff: {c['rating_diff']:+.2f}")
            print(f"    SF Computed: {c['computed_sf']:.2f}  "
                  f"SF Published: {c['published_sf']:.2f}")

            if c["game_details"]:
                print(f"\n    {'Opponent':<30} {'Result':>7} {'Play-Up':>8} "
                      f"{'Opp Wins':>9} {'Total':>7}")
                print(f"    {'-' * 65}")

                for gp in c["game_details"]:
                    opp_name = data.id_to_name.get(gp.opponent_id, f"ID:{gp.opponent_id}")
                    print(f"    {opp_name:<30} {gp.result_points:>7.1f} "
                          f"{gp.play_up_points:>8.1f} {gp.opponent_wins_points:>9.2f} "
                          f"{gp.total:>7.2f}")

                total = sum(gp.total for gp in c["game_details"])
                n = len(c["game_details"])
                print(f"    {'':30} {'':>7} {'':>8} {'Avg:':>9} {total/n:>7.2f}")

    # Aggregate metrics
    if all_diffs:
        n = len(all_diffs)
        mae = sum(abs(d) for d in all_diffs) / n
        max_err = max(abs(d) for d in all_diffs)
        mean_diff = sum(all_diffs) / n
        within_005 = sum(1 for d in all_diffs if abs(d) <= 0.05) / n * 100
        within_010 = sum(1 for d in all_diffs if abs(d) <= 0.10) / n * 100
        within_050 = sum(1 for d in all_diffs if abs(d) <= 0.50) / n * 100

        sf_mae = sum(abs(d) for d in all_sf_diffs) / n
        sf_max = max(abs(d) for d in all_sf_diffs)

        print(f"\n{'=' * 110}")
        print("AGGREGATE METRICS")
        print(f"{'=' * 110}")
        print(f"Teams compared:              {n}")
        print(f"Teams with discrepancy >0.05: {len(flagged)}")
        print()
        print(f"Power Rating:")
        print(f"  Mean Absolute Error (MAE): {mae:.4f}")
        print(f"  Max Absolute Error:        {max_err:.4f}")
        print(f"  Mean Bias (signed):        {mean_diff:+.4f}")
        print(f"  Within 0.05:               {within_005:.1f}%")
        print(f"  Within 0.10:               {within_010:.1f}%")
        print(f"  Within 0.50:               {within_050:.1f}%")
        print()
        print(f"Strength Factor:")
        print(f"  Mean Absolute Error (MAE): {sf_mae:.4f}")
        print(f"  Max Absolute Error:        {sf_max:.4f}")

        if mae < 0.05:
            print(f"\nVERDICT: Engine matches LHSAA formula (MAE < 0.05)")
        elif mae < 0.20:
            print(f"\nVERDICT: Engine is close but has minor discrepancies. "
                  f"Check per-game breakdowns above for root causes.")
        else:
            print(f"\nVERDICT: Significant discrepancies detected. "
                  f"Likely a formula interpretation issue or missing data.")
    else:
        print("\nNo teams matched between game results and published ratings.")
        print("Check that team names in your CSV match the seed data exactly.")

    # List teams in published data that were NOT in game results
    missing = [name for name in published if name not in data.name_to_id]
    if missing:
        print(f"\nTeams in published data but NOT in game results ({len(missing)}):")
        for name in sorted(missing)[:20]:
            print(f"  - {name}")
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.validate_engine <game_results_csv>")
        print("Example: python -m scripts.validate_engine data/game_results/2025_football_game_results.csv")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        sys.exit(1)

    validate(csv_path)


if __name__ == "__main__":
    main()
