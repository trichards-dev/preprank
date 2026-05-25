#!/usr/bin/env python3
"""
PrepRank pre-push mechanical checker.
Run from the repo root. Exits 0 (all clear) or 1 (violations found).
Used by the preprank-code-review skill and the git pre-push hook.
"""

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)


def run(cmd: str) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        return result.stdout
    except Exception:
        return ""


def get_diff() -> tuple[str, list[str]]:
    """Return (full diff text, list of changed file paths)."""
    branch = run("git branch --show-current").strip()
    # Check if we're on master already (comparing to previous commit)
    if branch == "master":
        diff = run("git diff HEAD~1...HEAD")
        files_raw = run("git diff HEAD~1...HEAD --name-only")
    else:
        diff = run("git diff master...HEAD")
        files_raw = run("git diff master...HEAD --name-only")
    files = [f.strip() for f in files_raw.splitlines() if f.strip()]
    return diff, files


def check_asyncpg(diff: str, files: list[str], r: CheckResult):
    """No asyncpg / async DB patterns in apps/api or packages/engine."""
    bad_patterns = [
        r"create_async_engine",
        r"asyncpg",
        r"async_sessionmaker",
        r"AsyncSession",
        r"from sqlalchemy\.ext\.asyncio",
    ]
    in_scope = [
        f for f in files
        if f.startswith("apps/api/") or f.startswith("packages/engine/")
    ]
    if not in_scope:
        r.passed.append("No API/engine files changed — asyncpg check skipped")
        return

    hits = []
    for pattern in bad_patterns:
        for line_num, line in enumerate(diff.splitlines(), 1):
            if line.startswith("+") and not line.startswith("+++"):
                if re.search(pattern, line):
                    hits.append(f"  Line ~{line_num}: {line.strip()[:120]}")
    if hits:
        r.blocks.append(
            "ASYNCPG / ASYNC DB — forbidden in apps/api and packages/engine "
            "(CLAUDE.md: 'Do not reintroduce async/asyncpg'):\n" + "\n".join(hits[:5])
        )
    else:
        r.passed.append("No asyncpg / async DB patterns detected")


def check_archive_patterns(diff: str, files: list[str], r: CheckResult):
    """No archive-branch patterns: /power-ratings routes, models/ package imports."""
    api_files = [f for f in files if f.startswith("apps/api/")]
    if not api_files:
        r.passed.append("No API files changed — archive pattern check skipped")
        return

    bad_patterns = [
        (r'prefix\s*=\s*["\']\/power-ratings', "Old /power-ratings route prefix (archive API)"),
        (r'from models\.', "from models. import (archive package structure; use app.models)"),
        (r'from app\.models\b', None),  # This is CORRECT — no flag
    ]

    hits = []
    for pattern, label in bad_patterns:
        if label is None:
            continue
        for line_num, line in enumerate(diff.splitlines(), 1):
            if line.startswith("+") and not line.startswith("+++"):
                if re.search(pattern, line):
                    hits.append(f"  [{label}] Line ~{line_num}: {line.strip()[:120]}")

    if hits:
        r.blocks.append(
            "ARCHIVE BRANCH PATTERNS detected — these belong to the retired pre-consolidation "
            "API, not the canonical /api/v1 implementation:\n" + "\n".join(hits[:5])
        )
    else:
        r.passed.append("No archive-branch patterns (power-ratings routes, models/ package)")


def check_web_api_contract(files: list[str], r: CheckResult):
    """If any router file changed, apps/web/src/lib/api.ts must also be in the diff."""
    router_files = [
        f for f in files
        if f.startswith("apps/api/app/routers/") and f.endswith(".py")
    ]
    if not router_files:
        r.passed.append("No router files changed — web→API contract check skipped")
        return

    api_ts_changed = "apps/web/src/lib/api.ts" in files
    if not api_ts_changed:
        r.blocks.append(
            "WEB→API CONTRACT DRIFT — router file(s) changed without updating "
            "apps/web/src/lib/api.ts:\n"
            + "\n".join(f"  {f}" for f in router_files)
            + "\n  If the endpoint shape didn't change, add a comment to api.ts confirming "
            "it was reviewed."
        )
    else:
        r.passed.append(
            f"Router change + api.ts update both present "
            f"({len(router_files)} router file(s) changed)"
        )


def check_port_references(diff: str, files: list[str], r: CheckResult):
    """
    Warn about hardcoded wrong port references.
    API = 8001, Web = 3001. localhost:8000 and localhost:8002 are wrong.
    """
    wrong_ports = [r"localhost:8000\b", r"localhost:8002\b"]
    hits = []
    for pattern in wrong_ports:
        for line_num, line in enumerate(diff.splitlines(), 1):
            if line.startswith("+") and not line.startswith("+++"):
                if re.search(pattern, line):
                    hits.append(f"  Line ~{line_num}: {line.strip()[:120]}")

    if hits:
        r.warnings.append(
            "PORT MISMATCH — API runs on 8001, web on 3001. "
            "Found potentially wrong port references:\n" + "\n".join(hits[:5])
            + "\n  Set NEXT_PUBLIC_API_URL explicitly rather than relying on defaults."
        )
    else:
        r.passed.append("Port references look correct (no stray :8000 or :8002)")


def check_secrets(diff: str, r: CheckResult):
    """Scan for hardcoded secrets, keys, or passwords in added lines."""
    secret_patterns = [
        (r'(?i)(secret_key|jwt_secret|api_key|private_key)\s*=\s*["\'][^"\']{8,}["\']', "Hardcoded key/secret"),
        (r'(?i)password\s*=\s*["\'][^"\']{4,}["\']', "Hardcoded password"),
        (r'sk-[a-zA-Z0-9]{20,}', "Possible API key (sk- prefix)"),
        (r'eyJ[a-zA-Z0-9_\-]{20,}', "Possible JWT token hardcoded"),
    ]
    hits = []
    for pattern, label in secret_patterns:
        for line_num, line in enumerate(diff.splitlines(), 1):
            if line.startswith("+") and not line.startswith("+++"):
                # Exclude lines that look like env var lookups or comments
                if re.search(r'os\.environ|os\.getenv|getenv|\.env|#', line):
                    continue
                if re.search(pattern, line):
                    # Redact the value before printing
                    redacted = re.sub(r'["\'][^"\']{4,}["\']', '"[REDACTED]"', line.strip())
                    hits.append(f"  [{label}] Line ~{line_num}: {redacted[:120]}")

    if hits:
        r.blocks.append(
            "SECRETS / CREDENTIALS in diff — never commit hardcoded secrets:\n"
            + "\n".join(hits[:5])
        )
    else:
        r.passed.append("No hardcoded secrets or credentials detected")


def check_bcrypt_pin(diff: str, files: list[str], r: CheckResult):
    """bcrypt must stay pinned to <4.1.0 (passlib compatibility)."""
    dep_files = [
        f for f in files
        if f.endswith("requirements.txt") or f.endswith("pyproject.toml")
    ]
    if not dep_files:
        return

    # Look for bcrypt version constraints being loosened
    for line_num, line in enumerate(diff.splitlines(), 1):
        if line.startswith("+") and not line.startswith("+++"):
            if re.search(r'bcrypt', line, re.IGNORECASE):
                # If pin is removed or loosened past 4.1.0
                if not re.search(r'<\s*4\.1', line) and not re.search(r'==\s*[34]\.', line):
                    r.blocks.append(
                        f"BCRYPT PIN — passlib requires bcrypt<4.1.0. "
                        f"The change at line ~{line_num} may loosen this: {line.strip()[:120]}"
                    )
                    return
    r.passed.append("bcrypt pin intact")


def check_destructive_migrations(diff: str, files: list[str], r: CheckResult):
    """Flag DROP TABLE / DROP COLUMN in new Alembic migration files."""
    migration_files = [
        f for f in files
        if "alembic/versions/" in f and f.endswith(".py")
    ]
    if not migration_files:
        return

    destructive = []
    for line_num, line in enumerate(diff.splitlines(), 1):
        if line.startswith("+") and not line.startswith("+++"):
            if re.search(r'\b(drop_table|drop_column|drop_constraint)\b', line, re.IGNORECASE):
                destructive.append(f"  Line ~{line_num}: {line.strip()[:120]}")

    if destructive:
        r.warnings.append(
            "DESTRUCTIVE MIGRATION — found DROP statements in new Alembic files. "
            "Verify this is safe on production data before pushing to master:\n"
            + "\n".join(destructive[:5])
        )
    else:
        r.passed.append(f"No destructive statements in {len(migration_files)} migration file(s)")


def check_simulation_in_routers(diff: str, files: list[str], r: CheckResult):
    """Simulation/math logic should live in packages/engine, not in API routers."""
    router_files = [f for f in files if f.startswith("apps/api/app/routers/")]
    if not router_files:
        return

    math_patterns = [
        r'\bnumpy\b|\bnp\.',
        r'\bscipy\b',
        r'monte.?carlo',
        r'elo_rating|power_rating.*formula',
        r'random\.gauss|random\.normal',
    ]
    hits = []
    for pattern in math_patterns:
        for line_num, line in enumerate(diff.splitlines(), 1):
            if line.startswith("+") and not line.startswith("+++"):
                if re.search(pattern, line, re.IGNORECASE):
                    hits.append(f"  Line ~{line_num}: {line.strip()[:120]}")

    if hits:
        r.warnings.append(
            "SIMULATION LOGIC IN ROUTERS — math/simulation code belongs in packages/engine, "
            "not in API routers. Routers should call the engine:\n" + "\n".join(hits[:5])
        )


def check_vercel_deploy_risk(files: list[str], r: CheckResult):
    """Flag when a push to master will trigger a Vercel auto-deploy."""
    branch = run("git branch --show-current").strip()
    web_files = [f for f in files if f.startswith("apps/web/")]
    root_pkg = [f for f in files if f in ("package.json", "package-lock.json")]

    if branch == "master" and (web_files or root_pkg):
        r.warnings.append(
            f"VERCEL AUTO-DEPLOY — pushing to master with web changes will immediately "
            f"deploy to production. Confirm `npm run build:web` passes locally first. "
            f"({len(web_files)} web file(s) + {len(root_pkg)} root package file(s) changed)"
        )


def main():
    # Verify we're in a git repo
    if not Path(".git").exists():
        print("⚠️  Run check_diff.py from the repo root (no .git found here)")
        sys.exit(1)

    diff, files = get_diff()

    if not files:
        print("✅  No changes detected vs master. Nothing to review.")
        sys.exit(0)

    r = CheckResult()

    check_asyncpg(diff, files, r)
    check_archive_patterns(diff, files, r)
    check_web_api_contract(files, r)
    check_port_references(diff, r)
    check_secrets(diff, r)
    check_bcrypt_pin(diff, files, r)
    check_destructive_migrations(diff, files, r)
    check_simulation_in_routers(diff, files, r)
    check_vercel_deploy_risk(files, r)

    # ── Print report ──────────────────────────────────────────────────────
    print("\n" + "━" * 56)
    print("PREPRANK MECHANICAL CHECK")
    print(f"Branch: {run('git branch --show-current').strip()}  |  "
          f"Files changed: {len(files)}")
    print("━" * 56)

    if r.blocks:
        print(f"\n❌  HARD BLOCKS ({len(r.blocks)})\n")
        for i, b in enumerate(r.blocks, 1):
            print(f"[{i}] {b}\n")

    if r.warnings:
        print(f"\n⚠️   WARNINGS ({len(r.warnings)})\n")
        for i, w in enumerate(r.warnings, 1):
            print(f"[{i}] {w}\n")

    if r.passed:
        print(f"\n✓  PASSED ({len(r.passed)})")
        for p in r.passed:
            print(f"   • {p}")

    print("\n" + "━" * 56)

    if r.blocks:
        print("VERDICT: ❌ BLOCKED — fix the items above before pushing.\n")
        sys.exit(1)
    elif r.warnings:
        print("VERDICT: ⚠️  WARNINGS — review before pushing.\n")
        sys.exit(0)
    else:
        print("VERDICT: ✅ MECHANICAL CHECKS PASSED — proceed to intelligent review.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
