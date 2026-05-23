"""Parse LHSAA official power-rating PDFs into ParsedPowerRating rows.

Supersedes the football-only scrape_lhsaa_pdf.py. This module is pure: no DB,
no env reads beyond FIRECRAWL_API_KEY when fallback fires. The loader
(load_lhsaa_official.py) owns orchestration and DB writes.

Usage as a library:
    from parse_lhsaa_pdf import parse_pdf
    rows = parse_pdf(entry_from_index_json)

Usage from CLI (single-URL debug):
    python -m scripts.parse_lhsaa_pdf --url <pdf_url> --sport Football --year 2025

Strategy:
    1. Cache the PDF to data/pdfs/lhsaa_official/<slug>.pdf (skip if cached).
    2. pdfplumber pass: extract tables, detect division/select per page,
       fall back to the index entry's values when the index pins them.
    3. If pdfplumber returns 0 rows, retry via Firecrawl SDK markdown output.
    4. Return list[ParsedPowerRating].
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pdfplumber


PDF_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "pdfs" / "lhsaa_official"

# Header regex — word-boundary anchored to avoid matching invalid roman like 'IIV'.
DIVISION_ROMAN_RE = re.compile(r"\bDivision\s+(I{1,3}|IV|V)\b", re.IGNORECASE)
DIVISION_NUM_RE = re.compile(r"\bDivision\s+(\d)\b", re.IGNORECASE)
DIVISION_CLASS_RE = re.compile(r"\bClass\s+([1-5]A|B|C)\b", re.IGNORECASE)
NUM_TO_ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV", "5": "V"}

# Date in the index "snapshot" field — examples: "10/30/2023 Final", "2/9/2024", "Final", "Week 10 Final"
SNAPSHOT_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


@dataclass
class ParsedPowerRating:
    rank: int | None
    school_name: str
    power_rating: float
    strength_factor: float | None
    wins: int
    losses: int
    division: str          # As it appears in the PDF/index: "I"–"V" or class letter "5A"/"B"/"C"
    select_status: str     # "Select" | "Non-Select" | "" (when unknown)
    season_year: int
    snapshot_date: date | None


def _slug(entry: dict) -> str:
    h = hashlib.sha1(entry["url"].encode("utf-8")).hexdigest()[:12]
    sport = entry.get("sport", "Unknown").replace(" ", "_")
    year = entry.get("season_year", "0000")
    return f"{sport}_{year}_{h}"


def _cached_path(entry: dict) -> Path:
    return PDF_CACHE_DIR / f"{_slug(entry)}.pdf"


def _markdown_path(entry: dict) -> Path:
    return PDF_CACHE_DIR / f"{_slug(entry)}.md"


def download_pdf(url: str, save_path: Path) -> Path:
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        save_path.write_bytes(response.content)
    return save_path


def parse_snapshot_date(snapshot: str) -> date | None:
    """Extract a date from the index entry's snapshot string.

    Returns None for "Final" / "Week 10 Final" style strings — these are
    end-of-season snapshots and the NULL-vs-NULL collision is handled by
    NULLS NOT DISTINCT on the LHSAA partial unique index.
    """
    if not snapshot:
        return None
    m = SNAPSHOT_DATE_RE.search(snapshot)
    if not m:
        return None
    month, day, year = map(int, m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_record(s: str) -> tuple[int, int]:
    m = re.match(r"(\d+)\s*-\s*(\d+)", (s or "").strip())
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


def detect_header(text: str) -> tuple[str | None, str | None]:
    """Read division (Roman or Class) and select_status from page text.

    Returns (division_or_None, select_status_or_None). Caller decides
    whether to use these or the index entry's authoritative values.
    """
    division: str | None = None
    select_status: str | None = None

    m = DIVISION_ROMAN_RE.search(text)
    if m:
        division = m.group(1).upper()
    else:
        m = DIVISION_NUM_RE.search(text)
        if m:
            division = NUM_TO_ROMAN.get(m.group(1))
        else:
            m = DIVISION_CLASS_RE.search(text)
            if m:
                division = m.group(1).upper()

    if re.search(r"\bnon[\s-]?select\b", text, re.IGNORECASE):
        select_status = "Non-Select"
    elif re.search(r"\bselect\b", text, re.IGNORECASE):
        select_status = "Select"

    return division, select_status


def _resolve_division_and_select(
    entry: dict,
    detected_division: str | None,
    detected_select: str | None,
) -> tuple[str, str]:
    """Index entry is authoritative when it pins a specific division/status."""
    index_div = entry.get("division", "all")
    if index_div != "all":
        division = index_div
    else:
        division = detected_division or "I"

    index_select = entry.get("select_status", "all")
    if index_select != "all":
        select_status = index_select
    else:
        select_status = detected_select or ""

    return division, select_status


def _compose_header(table: list[list[str | None]]) -> tuple[dict[str, int], int]:
    """Compose multi-row headers into a column-label → index map.

    LHSAA PDFs render headers across 1–3 stacked rows where each cell is a
    fragment (e.g. row[0]="POWER" / row[2]="RATING"). We walk rows until we
    see a numeric first cell (a data row) and concatenate non-empty cells
    per column. Returns (label_to_index, first_data_row_index).
    """
    parts: list[list[str]] = []
    data_start = 0
    for i, raw in enumerate(table):
        if not raw:
            continue
        cells = [(c or "").strip() for c in raw]
        if cells and cells[0].isdigit():
            data_start = i
            break
        for j, c in enumerate(cells):
            while len(parts) <= j:
                parts.append([])
            if c and c.upper() not in ("", "—", "-"):
                parts[j].append(c)
    labels = [" ".join(p).upper() for p in parts]
    label_to_idx = {label: i for i, label in enumerate(labels) if label}
    return label_to_idx, data_start


def _find_col(labels: dict[str, int], *needles: str) -> int | None:
    """Find the first column whose composed header contains all needles (AND)."""
    for label, idx in labels.items():
        if all(n in label for n in needles):
            return idx
    return None


def _extract_via_pdfplumber(pdf_path: Path, entry: dict) -> list[ParsedPowerRating]:
    rows: list[ParsedPowerRating] = []
    snapshot_date = parse_snapshot_date(entry.get("snapshot", ""))
    season_year = int(entry["season_year"])

    detected_div: str | None = None
    detected_select: str | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            d, s = detect_header(page_text)
            if d:
                detected_div = d
            if s:
                detected_select = s

            division, select_status = _resolve_division_and_select(
                entry, detected_div, detected_select
            )

            for table in page.extract_tables() or []:
                if not table:
                    continue
                labels, data_start = _compose_header(table)
                if not labels:
                    continue

                # Columns we care about. School + power rating are mandatory.
                # Avoid `or` chains because column 0 is a valid index but falsy.
                def pick(*tries):
                    for needles in tries:
                        n = needles if isinstance(needles, tuple) else (needles,)
                        i = _find_col(labels, *n)
                        if i is not None:
                            return i
                    return None

                school_idx = pick("SCHOOL")
                pr_idx = pick(("POWER", "RATING"), ("POWER", "RANKING"), "POWER")
                sf_idx = pick(("STRENGTH", "FACTOR"), "STRENGTH")
                rank_idx = pick("#", "RANK", "RK")
                if rank_idx is None:
                    rank_idx = 0
                wins_idx = pick("WINS")
                losses_idx = pick("LOSSES")
                record_idx = pick("RECORD", "W-L")

                if school_idx is None or pr_idx is None:
                    continue

                for raw in table[data_start:]:
                    if not raw:
                        continue
                    cells = [(c or "").strip() for c in raw]
                    if rank_idx >= len(cells) or not cells[rank_idx].isdigit():
                        continue
                    if school_idx >= len(cells) or pr_idx >= len(cells):
                        continue

                    school_name = cells[school_idx]
                    if not school_name:
                        continue
                    try:
                        rank = int(cells[rank_idx])
                        power_rating = float(cells[pr_idx])
                    except (ValueError, IndexError):
                        continue
                    strength_factor: float | None = None
                    if sf_idx is not None and sf_idx < len(cells) and cells[sf_idx]:
                        try:
                            strength_factor = float(cells[sf_idx])
                        except ValueError:
                            strength_factor = None

                    wins = losses = 0
                    if wins_idx is not None and losses_idx is not None:
                        try:
                            wins = int(cells[wins_idx]) if wins_idx < len(cells) else 0
                            losses = int(cells[losses_idx]) if losses_idx < len(cells) else 0
                        except ValueError:
                            wins = losses = 0
                    elif record_idx is not None and record_idx < len(cells):
                        wins, losses = parse_record(cells[record_idx])

                    rows.append(ParsedPowerRating(
                        rank=rank,
                        school_name=school_name,
                        power_rating=power_rating,
                        strength_factor=strength_factor,
                        wins=wins,
                        losses=losses,
                        division=division,
                        select_status=select_status,
                        season_year=season_year,
                        snapshot_date=snapshot_date,
                    ))
    return rows


def _extract_via_firecrawl(entry: dict) -> list[ParsedPowerRating]:
    """Firecrawl fallback. Logs raw markdown to disk for debugging.

    Raises if FIRECRAWL_API_KEY is not set. Caller should catch and continue.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise RuntimeError("FIRECRAWL_API_KEY not set; cannot use Firecrawl fallback")

    from firecrawl import FirecrawlApp  # local import — optional dependency
    app = FirecrawlApp(api_key=api_key)
    result = app.scrape_url(entry["url"], formats=["markdown"], parsers=["pdf"])
    markdown = getattr(result, "markdown", None) or (
        result.get("markdown") if isinstance(result, dict) else None
    ) or ""

    md_path = _markdown_path(entry)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")

    return _parse_markdown_tables(markdown, entry)


def _parse_markdown_tables(markdown: str, entry: dict) -> list[ParsedPowerRating]:
    """Parse pipe-delimited markdown tables (Firecrawl PDF output format).

    Falls back to whitespace-aligned columns if no pipe tables are found.
    """
    rows: list[ParsedPowerRating] = []
    snapshot_date = parse_snapshot_date(entry.get("snapshot", ""))
    season_year = int(entry["season_year"])

    detected_div: str | None = None
    detected_select: str | None = None

    # Pipe-delimited table rows look like: | 1 | School Name | 8-2 | 76.50 | 12.30 |
    pipe_row_re = re.compile(r"^\s*\|(.+)\|\s*$")
    for line in markdown.splitlines():
        d, s = detect_header(line)
        if d:
            detected_div = d
        if s:
            detected_select = s

        m = pipe_row_re.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        # Skip markdown separator rows like | --- | --- |
        if any(re.match(r"^-{3,}$", c.replace(":", "")) for c in cells):
            continue
        head_check = cells[0].upper() if cells else ""
        if any(h in head_check for h in ("RANK", "RK", "#", "SCHOOL")):
            continue
        if len(cells) < 4:
            continue
        try:
            rank = int(cells[0]) if cells[0].isdigit() else None
            school_name = cells[1]
            if not school_name:
                continue
            wins, losses = parse_record(cells[2])
            power_rating = float(cells[3])
            strength_factor = float(cells[4]) if len(cells) > 4 and cells[4] else None
        except (ValueError, IndexError):
            continue

        division, select_status = _resolve_division_and_select(
            entry, detected_div, detected_select
        )
        rows.append(ParsedPowerRating(
            rank=rank,
            school_name=school_name,
            power_rating=power_rating,
            strength_factor=strength_factor,
            wins=wins,
            losses=losses,
            division=division,
            select_status=select_status,
            season_year=season_year,
            snapshot_date=snapshot_date,
        ))
    return rows


def parse_pdf(entry: dict, force_firecrawl: bool = False) -> list[ParsedPowerRating]:
    """Parse one LHSAA PDF described by an index entry.

    Returns list of ParsedPowerRating rows. Caller is responsible for school
    name → team_id resolution and DB writes.
    """
    pdf_path = _cached_path(entry)
    if not pdf_path.exists():
        download_pdf(entry["url"], pdf_path)

    if force_firecrawl:
        return _extract_via_firecrawl(entry)

    rows = _extract_via_pdfplumber(pdf_path, entry)
    if rows:
        return rows

    # 0-row trigger only — small class-restricted PDFs may legitimately have
    # very few schools, so don't fall back on low row counts.
    return _extract_via_firecrawl(entry)


def _main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--sport", required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--division", default="all")
    p.add_argument("--select-status", default="all")
    p.add_argument("--snapshot", default="")
    p.add_argument("--force-firecrawl", action="store_true")
    args = p.parse_args()

    entry = {
        "sport": args.sport,
        "season_year": args.year,
        "division": args.division,
        "select_status": args.select_status,
        "snapshot": args.snapshot,
        "url": args.url,
    }
    rows = parse_pdf(entry, force_firecrawl=args.force_firecrawl)
    print(f"Parsed {len(rows)} rows from {args.url}")
    for r in rows[:5]:
        print(f"  {r.rank}\t{r.school_name}\t{r.power_rating}\t{r.division}\t{r.select_status}")
    if len(rows) > 5:
        print(f"  ... and {len(rows) - 5} more")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(_main())
