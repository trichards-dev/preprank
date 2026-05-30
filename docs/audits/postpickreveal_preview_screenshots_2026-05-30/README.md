# PostPickRevealCard — Phase 3.3.3 audit

**Captured:** 2026-05-30
**Approved by:** Reese Richards
**Verdict:** Clean integration. UI scenario (1) confirmed; analytics branch (c) confirmed; UI ships with agreement indicator, backend telemetry decoupled to v1.1.

## What this is

Phase 3.3.3 surface integration — adds the post-pick reveal to the
contest detail page (`app/pickem/[contestId]/page.tsx`) for the
locked-but-not-yet-scored window. Side-by-side YOUR PICK + PREPRANK
PREDICTS layout per Spec 4, with an agreement indicator chip.

## Read-gate findings (UI side)

Per the 3.3.3 read-gate discipline, audited
`apps/web/src/app/pickem/[contestId]/page.tsx` BEFORE implementation:

| Lines | Content | Pred-vs-actual? |
|---|---|---|
| 23–42 | Fetch contest + games + auth-conditional myPicks/results | No |
| 70–74 | Heading + contest meta | No |
| 76–81 | Grid of `<PickemCard>` — pre/post-pick state | Yes — but no model prediction |
| 83–97 | Submit button (open contests only) | No |
| 99–101 | Leaderboard link (scored contests) | No |

Current page has two states (open / scored). The
locked-but-not-yet-scored window had no dedicated rendering — Spec 4
fills that empty surface.

**Classification: Scenario (1) — clean add.** Pre-pick UX
(`isOpen → PickemCard`) untouched per "model prediction is NOT shown
before the user picks" decision.

## Analytics verification audit (branch c)

| Audit item | Finding |
|---|---|
| `track / capture / logEvent / analytics.*` calls in `apps/web` | None |
| `posthog / mixpanel / segment / amplitude / plausible / telemetry` references | None |
| `apps/web/package.json` analytics SDKs (incl. `@vercel/analytics`) | None |
| Alembic versions for events/analytics/telemetry/activity tables | None |
| `.github/workflows/` analytics jobs | None |
| Existing pre-pick "Pick Winner" flow telemetry | None |

**Branch (c) — no analytics infrastructure.** Decoupled Spec 3.5
(agreement-rate backend tracking) to v1.1 deliberate Thomas decision.
Filed trilemma in `claude-memory/.../open-questions.md`. UI ships
with visible agreement indicator only.

## Implementation

**New component** `apps/web/src/components/PostPickRevealCard.tsx`:
- Props: `game`, `pickedTeamId`, `pickedTeamName`, `forecast`
- Layout: two cards side-by-side on `md+`, stacks on mobile
- YOUR PICK card: team name + HOME/AWAY label
- PREPRANK PREDICTS card: wraps `<WinProbabilityWithCI variant="compact">` — layering pattern preserved (PostPickRevealCard composes, doesn't reimplement)
- Agreement chip: crimson tint when AGREED, steel-gray when DISAGREED, hidden when forecast unavailable
- No telemetry write — Spec 3.5 deferred per analytics branch (c)

**Page integration** `apps/web/src/app/pickem/[contestId]/page.tsx`:
- Three-state grid: `isOpen → PickemCard` / `!isOpen && !isScored && hasUserPicks → PostPickRevealCard` / `isScored → PickemCard with verdict`
- Parallel `Promise.all` fetch of forecasts in locked-no-scored state (one fetch per game; lazy in-memory API cache makes repeat views cheap)
- `useEffect` cleanup with cancellation flag
- Non-breaking fallback — `.catch(() => null)` on each forecast fetch; PREPRANK PREDICTS card shows "?" subtle indicator

## Color discipline (Reese 2026-05-30 visual review)

- AGREED → crimson tint (subtle positive)
- DISAGREED → steel-gray (neutral, NOT punitive red)
- Forecast unavailable → no chip rendered

Red for disagreement would feel punitive and undermine the
user-autonomy framing. Steel-gray respects the user's pick as a
considered call, not a mistake.

## Composite (8 cases)

| # | State | What to verify |
|---|---|---|
| 1 | Confident pick · AGREED | Crimson AGREED chip |
| 2 | Confident pick · DISAGREED | Steel-gray DISAGREED chip |
| 3 | Lean · AGREED | Mid-band CI on right card |
| 4 | Lean · DISAGREED | Disagreement framed honestly with mid-band CI |
| 5 | Long shot · AGREED | Wide CI band; AGREED chip |
| 6 | Long shot · DISAGREED | Wide CI band; DISAGREED chip — wide band frames disagreement context |
| 7 | Forecast unavailable | NO agreement chip; ? indicator |
| 8 | Baseball Lean · caveat | Spec 1a caveat flows through; agreement chip rendered |

## Capture method

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars \
  --window-size=1280,4400 \
  --screenshot=composite.png \
  http://localhost:3001/internal/postpickreveal-preview
```

## v1.1 deferred decisions filed (open-questions.md)

1. **Pick'em agreement-rate tracking infrastructure trilemma**
   (i) Establish analytics infrastructure + wire agreement event
   (ii) Build minimal custom telemetry (Supabase events table)
   (iii) Defer agreement-rate measurement until launch data justifies investment
2. **Pick'em locked-contest forecast fetch strategy**
   Promise.all (current) vs batch endpoint vs progressive rendering. Driven by typical contest size growth and latency observability.

## Cross-references

- `claude-memory/apps/preprank/decisions.md` 2026-05-30 — Phase 3.3.3
  ship with read-gate + analytics audit findings
- `claude-memory/apps/preprank/open-questions.md` 2026-05-30 — both
  v1.1 trilemmas filed
- `apps/web/src/components/PostPickRevealCard.tsx` — new component
- `apps/web/src/app/pickem/[contestId]/page.tsx` — three-state grid
- `apps/web/src/app/internal/postpickreveal-preview/page.tsx` —
  8-state preview with stable hard-coded sample data
- `apps/web/src/components/WinProbabilityWithCI.tsx` — primitive that
  PostPickRevealCard wraps (compact variant, default hideTeamNames)
