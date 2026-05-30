# GameCard + WinProbabilityWithCI — Phase 3.3.1 integration audit

**Captured:** 2026-05-30
**Approved by:** Reese Richards (Option A — hideTeamNames prop)
**Verdict:** Clean integration achieved after one design iteration.

## What this is

Phase 3.3.1 surface integration of `<WinProbabilityWithCI>` into the
shared `<GameCard>` primitive. Highest-leverage Phase 3.3 surface —
propagates to scores / teams/[id] / admin/replay pages via the existing
GameCard consumers.

## Artifacts

| File | Purpose |
|---|---|
| `composite.png` (v1) | FIRST capture — surfaced the team-name duplication finding |
| `composite_v2.png` | After `hideTeamNames` prop landed — integration cleaned up |

Both kept for the before/after audit trail.

## v1 finding: team-name duplication

Initial integration (commit `6f4c383` for the component, GameCard
integration in this turn) nested `<WinProbabilityWithCI>` inside
GameCard. Both rendered team names. The composite showed:

```
[GameCard scoreboard row 1]  North Caddo · –
[GameCard scoreboard row 2]  Airline · –
[WinProb block row 1]        North Caddo · 89%
[WinProb block row 2]        Airline · 11%
```

→ Team names appeared TWICE per card. Visible UX issue.

**Root cause:** WinProbabilityWithCI was designed as a *standalone*
primitive carrying its own team-name labels. GameCard *also* carries
team-name labels (existing scoreboard rows). Nesting duplicated them.
This tension wasn't visible until 3.3.1 — the halt-gate worked as
designed.

## Resolution: Option A — `hideTeamNames` prop

Surfaced 3 paths (A: prop, B: inline-into-scoreboard, C: replace
scoreboard pre-game). Reese chose A for smallest scope + lowest
regression risk for Sept 1 timeline. Options B/C deferred — B
rejected (couples GameCard tightly to forecast presence); C filed as
v1.1 deliberate decision (`pre_game_gamecard_identity_review`).

**Implementation:**
- Added `hideTeamNames?: boolean` prop to WinProbabilityWithCI (default false)
- When `hideTeamNames=true`, renders only: bar + percentages + tier chip + caveat
- GameCard passes `hideTeamNames={true}` so its scoreboard rows do the team-name work
- Default behavior unchanged — standalone consumers (game detail, methodology) get the team names

## v2 verification (composite_v2.png)

7 states confirmed:

| # | State | Outcome |
|---|---|---|
| 1 | Scheduled + Confident pick | Bar narrow, CONFIDENT PICK chip, no duplication |
| 2 | Scheduled + Lean | Bar medium, LEAN chip, no duplication |
| 3 | Scheduled + Long shot (playoff) | Bar wide, LONG SHOT chip, no duplication |
| 4 | Scheduled + forecast unavailable | `? vs ?` centered, prose sub-line |
| 5 | Scheduled + Baseball caveat | ⓘ caveat below LEAN chip |
| 6 | Final game | Forecast block suppressed (v1.0 keeps post-game UX clean) |
| 7 | Scheduled, NO forecast prop | Existing scoreboard-only rendering preserved — non-breaking |

Cases 6 and 7 confirm the integration is backwards-compatible:
existing GameCard consumers (scores / teams/[id] / admin/replay) that
don't pass the new `forecast` prop render exactly as before.

## Capture method

Headless Chrome (installed Chrome.app, not a transient install):

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars \
  --window-size=1280,2600 \
  --screenshot=composite_v2.png \
  http://localhost:3001/internal/gamecard-preview
```

`/internal/gamecard-preview` route renders all 7 states with stable
hard-coded sample data; reproducible without DB or API state.

## v1.1 deferred decision item (filed in open-questions.md)

**Pre-game GameCard identity review:** should pre-game cards be
prediction-first (forecast-as-primary-element, scoreboard-rows-
suppressed-until-final) or score-first-with-forecast-overlay? Brand
spec voice positions PrepRank as prediction-driven, supporting
prediction-first identity. Option C-style restructure is real
architectural work; deferred to deliberate post-launch Thomas call.

## Cross-references

- `claude-memory/apps/preprank/decisions.md` 2026-05-30 — Phase 3.3.1
  duplication finding + Option A selection
- `claude-memory/apps/preprank/open-questions.md` 2026-05-30 — v1.1
  pre-game GameCard identity decision item
- `apps/web/src/components/WinProbabilityWithCI.tsx` — added
  `hideTeamNames` prop
- `apps/web/src/components/GameCard.tsx` — passes
  `hideTeamNames={true}`
- `apps/web/src/app/internal/gamecard-preview/page.tsx` — 7-state preview
- `apps/web/src/app/internal/winprob-preview/page.tsx` — extended
  with k/l hideTeamNames cases; see
  `docs/audits/winprob_preview_screenshots_2026-05-30/composite_v2_hideTeamNames.png`
