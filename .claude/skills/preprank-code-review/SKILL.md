---
name: preprank-code-review
description: >
  PrepRank-specific pre-push code review gate. Run this EVERY TIME before pushing to any remote
  branch on the PrepRank monorepo, and especially before pushing to master. Catches the exact
  failure modes that have burned this project before: asyncpg creeping back in, port number
  mismatches, web→API contract drift, sessions accidentally writing outside their scope, and
  changes to master that will auto-deploy a broken Vercel build. Invoke with /preprank-code-review
  whenever: a commit is about to be pushed, a PR is being prepared, multiple concurrent sessions
  have been running, or after any significant feature branch work. This is mandatory — do not skip
  it, do not push before running it.
---

# PrepRank Code Review Gate

You are acting as the PrepRank code master. Your job is to review the diff between the current
branch and master, flag every violation of the project's hard rules, and give a clear go / no-go
decision before anything is pushed.

## Step 1 — Get the diff

Run both of these and hold on to the output:

```bash
# Full diff between this branch and master
git diff master...HEAD --stat
git diff master...HEAD
```

If the branch IS master (i.e., comparing master to itself), run instead:
```bash
git diff HEAD~1...HEAD --stat
git diff HEAD~1...HEAD
```

Also run:
```bash
git log master..HEAD --oneline   # commits being pushed
git branch --show-current         # confirm which branch this is
```

## Step 2 — Run the mechanical checker

The bundled script does the fast, pattern-based checks. Run it from the repo root:

```bash
python .claude/skills/preprank-code-review/scripts/check_diff.py
```

The script exits 0 (pass) or 1 (fail) and prints a structured report. Read its output carefully —
every item it flags is a hard rule, not a suggestion.

## Step 3 — Intelligent review

After the script, do your own read of the diff with these questions in mind:

### A. Scope integrity
Identify what kind of session produced these changes. A healthy diff is focused:
- **API session**: changes in `apps/api/` and possibly `packages/shared/` — nothing in `apps/web/` or `apps/mobile/`
- **Web session**: changes in `apps/web/` and possibly `packages/shared/` — nothing in `apps/api/` or `apps/mobile/`
- **Mobile session**: changes in `apps/mobile/` and possibly `packages/shared/` — nothing in `apps/api/` or `apps/web/`
- **Engine session**: changes in `packages/engine/` only — nothing in any `apps/` directory
- **Multi-package PRs are fine** when intentional (e.g., a shared type change that ripples to web + mobile)

Flag any files that appear outside the expected scope. Don't block on it — call it out and ask the
developer to confirm it was intentional.

### B. Web → API contract integrity
This is the most common silent breakage. If **any router file** under `apps/api/app/routers/` is
in the diff (new endpoint, renamed path, changed response shape, removed field), then
`apps/web/src/lib/api.ts` **must also be in the diff**. If it isn't, that's a hard BLOCK.

The canonical routers are: `schools`, `teams`, `games`, `ratings`, `simulations`, `auth`,
`subscriptions`, `favorites`, `pickem`, `share`, `hype`, `scenarios`, `admin_replay`.

### C. Simulation logic placement
Simulation and power-rating math belongs in `packages/engine`, not in API routers. If you see
statistical logic (numpy, scipy, Monte Carlo loops, ELO calculations) appearing in
`apps/api/app/routers/`, flag it. Routers should call the engine, not implement the math.

### D. Vercel auto-deploy risk
**Any push to master auto-deploys to production via Vercel.** If the diff touches `apps/web/` or
the root `package.json` / `package-lock.json`, confirm the web build would pass before blessing
the push. If possible, note: "run `npm run build:web` locally before pushing."

### E. Database migration safety
If `apps/api/alembic/versions/` has new migration files, check that the migration is additive
(new tables, new nullable columns, new indexes). Destructive migrations (DROP TABLE, DROP COLUMN,
ALTER that removes NOT NULL) on production need special care — flag them prominently.

### F. Environment / secrets hygiene
Scan for any hardcoded secrets, API keys, passwords, or JWT secrets appearing in the diff. Even
in test files. This is an auto-block.

## Step 4 — Compose the report

Use this exact structure:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PREPRANK CODE REVIEW — [branch name] → master
[timestamp]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VERDICT: ✅ CLEAR TO PUSH  /  ❌ BLOCKED  /  ⚠️ PUSH WITH CAUTION

Files changed: N  |  Insertions: +N  |  Deletions: -N

── HARD BLOCKS (must fix before pushing) ──────────────────
[List each violation with file + line reference, or "None"]

── WARNINGS (review before pushing) ──────────────────────
[Scope drift, Vercel deploy risk, migration notes, or "None"]

── CHECKS PASSED ──────────────────────────────────────────
✓ No asyncpg / async DB patterns
✓ Port references correct (8001 for API, 3001 for web)
✓ No archive-branch patterns (/power-ratings, models/ package)
✓ Web→API contract consistent
✓ No hardcoded secrets
✓ Simulation logic stays in engine
[Add or remove based on what was actually in scope]

── COMMITS IN THIS PUSH ───────────────────────────────────
[git log output]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

If the verdict is **BLOCKED**, do not proceed. Tell the developer exactly what to fix.
If the verdict is **PUSH WITH CAUTION**, list what to watch and offer to help fix it.
If the verdict is **CLEAR**, say so confidently.

## Hard rules reference

These come from CLAUDE.md and are non-negotiable:

| Rule | What to look for | Action |
|------|-----------------|--------|
| No asyncpg in API/engine | `create_async_engine`, `asyncpg`, `async_sessionmaker`, `AsyncSession` appearing in `apps/api/` or `packages/engine/` | BLOCK |
| Correct API prefix | Route paths like `/power-ratings/` (no `/api/v1/`) in `apps/api/` | BLOCK |
| No archive patterns | `from models.` imports (archive package structure) in `apps/api/` | BLOCK |
| Port 8001 for API | Hardcoded `localhost:8000` or `localhost:8002` in `apps/web/` or test files when referring to the API | WARN |
| Web→API contract | Router change without `api.ts` update | BLOCK |
| No secrets in diff | Any string matching key/secret/password patterns in values | BLOCK |
| bcrypt < 4.1.0 | If `requirements.txt` / `pyproject.toml` changes loosen the bcrypt pin | BLOCK |
| Engine owns math | Simulation logic in routers | WARN |
| Destructive migrations | DROP TABLE/COLUMN in new Alembic files | WARN (escalate) |
