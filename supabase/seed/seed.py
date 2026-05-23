#!/usr/bin/env python3
"""
PrepRank seed script — loads LHSAA sports and 2025 football power ratings from CSV.

Usage:
    python seed.py
    python seed.py --database-url postgresql://user:pass@host:5432/dbname
    python seed.py --csv /path/to/ratings.csv
"""

import argparse
import csv
import os
import sys

import psycopg2

DIVISION_TO_CLASSIFICATION = {
    "I": "5A",
    "II": "4A",
    "III": "3A",
    "IV": "2A",
    "V": "1A",
}

SPORTS_SQL = """
INSERT INTO sports (name, season, has_power_rating) VALUES
    ('Football', 'fall', TRUE),
    ('Volleyball', 'fall', TRUE),
    ('Cross Country', 'fall', FALSE),
    ('Swimming', 'fall', FALSE),
    ('Boys Basketball', 'winter', TRUE),
    ('Girls Basketball', 'winter', TRUE),
    ('Wrestling', 'winter', FALSE),
    ('Bowling', 'winter', FALSE),
    ('Indoor Track and Field', 'winter', FALSE),
    ('Gymnastics', 'winter', FALSE),
    ('Baseball', 'spring', TRUE),
    ('Softball', 'spring', TRUE),
    ('Boys Soccer', 'spring', TRUE),
    ('Girls Soccer', 'spring', TRUE),
    ('Tennis', 'spring', FALSE),
    ('Golf', 'spring', FALSE),
    ('Outdoor Track and Field', 'spring', FALSE),
    ('Boys Golf', 'spring', FALSE),
    ('Girls Golf', 'spring', FALSE),
    ('Boys Tennis', 'spring', FALSE),
    ('Girls Tennis', 'spring', FALSE),
    ('Boys Swimming', 'fall', FALSE),
    ('Girls Swimming', 'fall', FALSE)
ON CONFLICT DO NOTHING;
"""


def parse_args():
    parser = argparse.ArgumentParser(description="Seed PrepRank database with sports and football power ratings.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "postgresql://preprank:preprank@localhost:5432/preprank"),
        help="PostgreSQL connection string (default: DATABASE_URL env var or local dev)",
    )
    parser.add_argument(
        "--csv",
        default=os.path.join(os.path.dirname(__file__), "..", "..", "data", "seed", "2025_football_power_ratings_final.csv"),
        help="Path to the football power ratings CSV file",
    )
    return parser.parse_args()


def seed_sports(cur):
    """Insert all 23 LHSAA sports (idempotent)."""
    cur.execute(SPORTS_SQL)
    print(f"  Sports seeded (INSERT ON CONFLICT DO NOTHING)")


def get_football_sport_id(cur):
    cur.execute("SELECT id FROM sports WHERE name = 'Football'")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Football sport not found after seeding — check sports table.")
    return row[0]


def load_csv(csv_path):
    """Read the CSV and return list of row dicts."""
    csv_path = os.path.abspath(csv_path)
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"  Loaded {len(rows)} rows from {csv_path}")
    return rows


def seed_schools(cur, rows):
    """Insert schools from CSV rows. Returns dict of school_name -> school_id."""
    inserted = 0
    for row in rows:
        name = row["school"].strip()
        division = row["division"].strip()
        classification = DIVISION_TO_CLASSIFICATION.get(division, division)
        select_status = row["select_status"].strip()

        # Check if school already exists
        cur.execute("SELECT id FROM schools WHERE name = %s", (name,))
        existing = cur.fetchone()
        if existing:
            continue

        cur.execute(
            "INSERT INTO schools (name, classification, division, select_status) VALUES (%s, %s, %s, %s)",
            (name, classification, division, select_status),
        )
        inserted += 1

    # Build name -> id map
    cur.execute("SELECT id, name FROM schools")
    school_map = {r[1]: r[0] for r in cur.fetchall()}
    print(f"  Schools: {inserted} inserted, {len(school_map)} total")
    return school_map


def seed_teams(cur, rows, school_map, football_id):
    """Insert a football team for each school. Returns dict of school_name -> team_id."""
    inserted = 0
    for row in rows:
        name = row["school"].strip()
        division = row["division"].strip()
        select_status = row["select_status"].strip()
        school_id = school_map.get(name)
        if school_id is None:
            print(f"  WARNING: No school_id for '{name}', skipping team")
            continue

        cur.execute(
            """INSERT INTO teams (school_id, sport_id, season_year, division, select_status)
               VALUES (%s, %s, 2025, %s, %s)
               ON CONFLICT (school_id, sport_id, season_year) DO NOTHING""",
            (school_id, football_id, division, select_status),
        )
        if cur.rowcount > 0:
            inserted += 1

    # Build school_name -> team_id map
    cur.execute(
        """SELECT t.id, s.name
           FROM teams t JOIN schools s ON t.school_id = s.id
           WHERE t.sport_id = %s AND t.season_year = 2025""",
        (football_id,),
    )
    team_map = {r[1]: r[0] for r in cur.fetchall()}
    print(f"  Teams: {inserted} inserted, {len(team_map)} total")
    return team_map


def seed_power_ratings(cur, rows, team_map):
    """Insert power ratings for each team."""
    # Count teams per division for total_teams_in_division
    division_counts = {}
    for row in rows:
        div = row["division"].strip()
        division_counts[div] = division_counts.get(div, 0) + 1

    # Build school -> division lookup
    school_division = {row["school"].strip(): row["division"].strip() for row in rows}

    inserted = 0
    for row in rows:
        name = row["school"].strip()
        team_id = team_map.get(name)
        if team_id is None:
            print(f"  WARNING: No team_id for '{name}', skipping rating")
            continue

        rank = int(row["rank"])
        power_rating = float(row["power_rating"])
        strength_factor = float(row["strength_factor"])
        division = row["division"].strip()
        total_in_div = division_counts[division]

        cur.execute(
            """INSERT INTO power_ratings (team_id, week_number, season_year, power_rating, strength_factor, rank_in_division, total_teams_in_division, source)
               VALUES (%s, 11, 2025, %s, %s, %s, %s, 'engine')
               ON CONFLICT (team_id, week_number, season_year) WHERE source = 'engine'
               DO UPDATE SET
                 power_rating = EXCLUDED.power_rating,
                 strength_factor = EXCLUDED.strength_factor,
                 rank_in_division = EXCLUDED.rank_in_division,
                 total_teams_in_division = EXCLUDED.total_teams_in_division""",
            (team_id, power_rating, strength_factor, rank, total_in_div),
        )
        if cur.rowcount > 0:
            inserted += 1

    print(f"  Power ratings: {inserted} inserted")
    for div, count in sorted(division_counts.items()):
        print(f"    Division {div}: {count} teams")


def main():
    args = parse_args()

    print(f"Connecting to: {args.database_url.split('@')[-1] if '@' in args.database_url else args.database_url}")
    conn = psycopg2.connect(args.database_url)
    try:
        cur = conn.cursor()

        print("\n1. Seeding sports...")
        seed_sports(cur)

        print("\n2. Loading CSV...")
        rows = load_csv(args.csv)

        print("\n3. Getting football sport ID...")
        football_id = get_football_sport_id(cur)
        print(f"  Football sport_id = {football_id}")

        print("\n4. Seeding schools...")
        school_map = seed_schools(cur, rows)

        print("\n5. Seeding teams...")
        team_map = seed_teams(cur, rows, school_map, football_id)

        print("\n6. Seeding power ratings...")
        seed_power_ratings(cur, rows, team_map)

        conn.commit()
        print("\nDone. All data committed.")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
