"""CLI entry for the Phase 0 audit.

    python -m scripts.audit run --sports all --seasons 2021-2025
    python -m scripts.audit run --sports football --seasons 2025 --skip-cross-source
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from scripts.audit import run_full_audit
from scripts.audit.db import ALL_SPORTS, supabase_client_factory


def _parse_seasons(spec: str) -> list[int]:
    out: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif chunk:
            out.add(int(chunk))
    return sorted(out)


def _parse_sports(spec: str) -> list[str]:
    if spec.lower() in ("all", "*"):
        return list(ALL_SPORTS)
    # Accept comma list; match case-insensitively against ALL_SPORTS.
    requested = [s.strip() for s in spec.split(",") if s.strip()]
    canonical_by_lower = {s.lower(): s for s in ALL_SPORTS}
    out: list[str] = []
    for r in requested:
        c = canonical_by_lower.get(r.lower())
        if c is None:
            raise SystemExit(f"unknown sport: {r!r}. choices: {ALL_SPORTS}")
        out.append(c)
    return out


def main(argv: list[str] | None = None) -> int:
    # Load apps/api/.env so SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are available
    # without needing the user to export them first.
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / "apps" / "api" / ".env")

    p = argparse.ArgumentParser(prog="python -m scripts.audit")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run all Phase 0 checks")
    p_run.add_argument("--sports", default="all", help="'all' or comma-list (default: all)")
    p_run.add_argument("--seasons", default="2021-2025", help="e.g. '2021-2025' or '2022,2024'")
    p_run.add_argument("--output-dir", default="reports/data_audit")
    p_run.add_argument("--no-persist-db", action="store_true",
                       help="skip writing rows to data_audit_results")
    p_run.add_argument("--skip-cross-source", action="store_true",
                       help="skip check 0.7 (PDF parsing — slow first run)")
    p_run.add_argument("--run-id", default=None, help="reuse a specific run_id (otherwise UUID4)")
    p_run.add_argument("--reclass-threshold", type=float, default=0.50,
                       help="fraction of teams that must change division for a "
                            "reclassification event to be flagged (default 0.50)")

    args = p.parse_args(argv)

    if args.cmd != "run":
        p.print_help()
        return 2

    sports = _parse_sports(args.sports)
    seasons = _parse_seasons(args.seasons)

    sb = supabase_client_factory()
    run_id, results, reclass_events, paths = run_full_audit(
        sb,
        sports=sports,
        seasons=seasons,
        output_dir=args.output_dir,
        persist=not args.no_persist_db,
        skip_cross_source=args.skip_cross_source,
        run_id=args.run_id,
        reclass_threshold=args.reclass_threshold,
    )

    # Compact stdout summary
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    print()
    print(f"=== Phase 0 audit run_id={run_id} ===")
    print(f"results: {by_status}")
    print(f"reclass events: {len(reclass_events)}")
    print(f"SUMMARY:   {paths['summary_md']}")
    print(f"anomalies: {paths['anomalies_csv']}")
    print(f"per-(sport,season) JSON: {paths['json_dir']}")
    return 0 if by_status.get("fail", 0) == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
