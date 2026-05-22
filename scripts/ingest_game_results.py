"""Ingest game-by-game results CSV and build the data structures needed by the engine.

Usage:
    python -m scripts.ingest_game_results data/game_results/2025_football_game_results.csv

CSV columns:
    season_year, week, team_name, opponent_name, team_score, opponent_score,
    is_home, is_district, opponent_division, opponent_select_status

The ingestion does the following:
1. Reads every row as one team's perspective of a game
2. Builds TeamRecord objects with win/loss totals derived from the data
3. Builds GameResult lists per team
4. Cross-references opponent records from the seed CSV (data/seed/) for
   teams not in the game results file (out-of-state, other brackets, etc.)
5. Returns structures ready for calculate_all_power_ratings()

Design decision: Each row is ONE team's view. If you have both teams' perspectives
in the file, duplicates are detected and collapsed. If you only have one side,
the opponent's game is inferred automatically.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

from engine.types import TeamRecord, GameResult


SEED_CSV = Path(__file__).parent.parent / "data" / "seed" / "2025_football_power_ratings_final.csv"


@dataclass
class RawGame:
    season_year: int
    week: int
    team_name: str
    opponent_name: str
    team_score: int
    opponent_score: int
    is_home: bool
    is_district: bool
    opponent_division: str
    opponent_select_status: str


@dataclass
class IngestedData:
    """Everything the engine needs to compute power ratings."""
    records: dict[int, TeamRecord]          # team_id -> TeamRecord
    games: dict[int, list[GameResult]]      # team_id -> list of GameResults
    name_to_id: dict[str, int]              # team_name -> team_id
    id_to_name: dict[int, str]              # team_id -> team_name
    warnings: list[str] = field(default_factory=list)


def _parse_bool(val: str) -> bool:
    return val.strip().upper() in ("TRUE", "1", "YES", "Y")


def load_seed_data() -> dict[str, dict]:
    """Load the seed CSV to get division/select_status/record for all teams."""
    teams = {}
    if not SEED_CSV.exists():
        return teams
    with open(SEED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            teams[row["school"].strip()] = row
    return teams


def load_game_results(csv_path: Path) -> list[RawGame]:
    """Parse game results CSV into RawGame objects."""
    games = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            try:
                games.append(RawGame(
                    season_year=int(row["season_year"]),
                    week=int(row["week"]),
                    team_name=row["team_name"].strip(),
                    opponent_name=row["opponent_name"].strip(),
                    team_score=int(row["team_score"]),
                    opponent_score=int(row["opponent_score"]),
                    is_home=_parse_bool(row["is_home"]),
                    is_district=_parse_bool(row.get("is_district", "FALSE")),
                    opponent_division=row.get("opponent_division", "").strip(),
                    opponent_select_status=row.get("opponent_select_status", "").strip(),
                ))
            except (ValueError, KeyError) as e:
                print(f"WARNING: Skipping row {i}: {e}")
    return games


def ingest(csv_path: Path) -> IngestedData:
    """Ingest a game results CSV and return engine-ready data structures.

    Handles:
    - Assigning stable team IDs
    - Deduplicating games reported from both sides
    - Inferring opponent game results when only one side is reported
    - Looking up division/classification from seed data for teams not in the CSV
    """
    raw_games = load_game_results(csv_path)
    seed_data = load_seed_data()
    warnings: list[str] = []

    # Collect all unique team names
    all_names: set[str] = set()
    for g in raw_games:
        all_names.add(g.team_name)
        all_names.add(g.opponent_name)

    # Assign IDs
    name_to_id: dict[str, int] = {}
    id_to_name: dict[int, str] = {}
    for i, name in enumerate(sorted(all_names), start=1):
        name_to_id[name] = i
        id_to_name[i] = name

    # Track wins/losses per team (derived from game results, not seed CSV)
    wins: dict[str, int] = {n: 0 for n in all_names}
    losses: dict[str, int] = {n: 0 for n in all_names}

    # Track which games we've already seen (to deduplicate)
    # Key: (min(team_a, team_b), max(team_a, team_b), week)
    seen_games: set[tuple[str, str, int]] = set()

    # Build game results per team
    team_game_results: dict[int, list[GameResult]] = {name_to_id[n]: [] for n in all_names}

    # Division/classification lookup
    def get_division(name: str, fallback: str = "") -> str:
        if name in seed_data:
            return seed_data[name].get("division", fallback)
        return fallback

    def get_select_status(name: str, fallback: str = "Non-Select") -> str:
        if name in seed_data:
            return seed_data[name].get("select_status", fallback)
        return fallback

    # All seed teams are football, so classification isn't in our CSV.
    # LHSAA football doesn't use classification for power ratings (it uses division).
    # We'll default classification to "5A" and rely on division for play-up calc.
    def get_classification(name: str) -> str:
        # Football power ratings are organized by division, not classification.
        # Classification only matters for play-up points against other classifications.
        # For teams within the same bracket, play-up is always 0.
        return "5A"

    for g in raw_games:
        a, b = g.team_name, g.opponent_name
        key = (min(a, b), max(a, b), g.week)

        if key in seen_games:
            continue  # Already processed from the other team's perspective
        seen_games.add(key)

        team_won = g.team_score > g.opponent_score
        team_id = name_to_id[a]
        opp_id = name_to_id[b]

        if team_won:
            wins[a] += 1
            losses[b] += 1
        else:
            losses[a] += 1
            wins[b] += 1

        # Opponent division/select_status: prefer what's in the CSV row,
        # fall back to seed data
        opp_div = g.opponent_division or get_division(b)
        opp_sel = g.opponent_select_status or get_select_status(b)
        team_div = get_division(a)
        team_sel = get_select_status(a)

        if not opp_div:
            warnings.append(f"Week {g.week}: No division for opponent '{b}' (vs {a})")
            opp_div = "I"
        if not team_div:
            warnings.append(f"Week {g.week}: No division for team '{a}'")
            team_div = "I"

        # Add game from team's perspective
        team_game_results[team_id].append(GameResult(
            team_id=team_id,
            opponent_id=opp_id,
            won=team_won,
            opponent_division=opp_div,
            opponent_classification=get_classification(b),
        ))

        # Add game from opponent's perspective (inferred)
        team_game_results[opp_id].append(GameResult(
            team_id=opp_id,
            opponent_id=team_id,
            won=not team_won,
            opponent_division=team_div,
            opponent_classification=get_classification(a),
        ))

    # Build TeamRecord objects
    records: dict[int, TeamRecord] = {}
    for name in all_names:
        tid = name_to_id[name]
        records[tid] = TeamRecord(
            team_id=tid,
            classification=get_classification(name),
            division=get_division(name, "I"),
            select_status=get_select_status(name),
            wins=wins[name],
            losses=losses[name],
        )

    # Cross-check against seed data
    for name in all_names:
        if name in seed_data:
            seed_w = int(seed_data[name]["wins"])
            seed_l = int(seed_data[name]["losses"])
            actual_w = wins[name]
            actual_l = losses[name]
            if actual_w != seed_w or actual_l != seed_l:
                warnings.append(
                    f"{name}: game results give {actual_w}-{actual_l} "
                    f"but seed CSV says {seed_w}-{seed_l}"
                )

    return IngestedData(
        records=records,
        games=team_game_results,
        name_to_id=name_to_id,
        id_to_name=id_to_name,
        warnings=warnings,
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.ingest_game_results <csv_path>")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        sys.exit(1)

    data = ingest(csv_path)

    print(f"Ingested {sum(len(g) for g in data.games.values()) // 2} unique games")
    print(f"Teams: {len(data.records)}")
    print()

    if data.warnings:
        print(f"WARNINGS ({len(data.warnings)}):")
        for w in data.warnings:
            print(f"  - {w}")
        print()

    # Print summary
    print(f"{'Team':<35} {'W':>3} {'L':>3} {'Games':>5} {'Division':>8} {'Select':>11}")
    print("-" * 70)
    for tid in sorted(data.records, key=lambda t: data.id_to_name[t]):
        rec = data.records[tid]
        name = data.id_to_name[tid]
        num_games = len(data.games[tid])
        print(f"{name:<35} {rec.wins:>3} {rec.losses:>3} {num_games:>5} "
              f"{rec.division:>8} {rec.select_status:>11}")


if __name__ == "__main__":
    main()
