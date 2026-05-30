# GameCard + Model Details expand — Phase 3.3.4 audit (REVISED → 3.3.4b)

**Captured:** 2026-05-30
**Approved by:** Reese Richards (Option 2 selected after 4-section preview comparison; revised same day to remove coefficient exposure)
**Verdict:** Clean integration. Premium-conditional expand with single-expand-only behavior. Phase 3.3.4b (later same day) removed raw coefficient exposure entirely.

## Pre-commit revision (3.3.4b · 2026-05-30 same day)

Thomas raised: paywalling raw β coefficients doesn't protect IP — a
competitor pays once, scrapes β values, reverse-engineers the model.
**Real protection requires not exposing coefficients at any tier.**

**API exposure status at time of revision:** ZERO. The deployed Vercel
web app calls `api.preprank.com` which does not resolve (HTTP 000 / DNS
fails). No premium user has ever seen the original 3.3.4 payload in
production. Revision lands cleanly with no rollback urgency.

**What 3.3.4 originally shipped (preserved as `composite_pre_3_3_4b.png`):**
- `PremiumDetail.model_coefficients`: raw β₀–β₆ floats
- `PredictedDecileReliability`: n_games, gap, mean_predicted, mean_observed numerics

**What 3.3.4b replaces it with (rendered in `composite_v2_factor_impact.png`):**
- `PremiumDetail.factor_contributions`: qualitative impact buckets ("Opponent strength · HIGH IMPACT", etc.) — derived server-side from coefficient magnitudes, raw values never leave the engine
- `PredictedDecileReliability.description`: prose statement ("Predictions in this range typically match observed outcomes within our confidence band.") — no n/gap/predicted/observed numerics

**Six factor labels (engine-side beta semantic map; raw beta names + magnitudes never exit):**
| Internal | Public label |
|---|---|
| beta_0 | (intercept — not exposed as a "factor"; baseline only) |
| beta_1 | Opponent strength |
| beta_2 | Home advantage |
| beta_3 | Scoring margin |
| beta_4 | Offensive/defensive balance |
| beta_5 | Early-season carryover |
| beta_6 | Recent form |

**Impact bucket derivation (server-side `_impact_buckets()` in `packages/engine/src/engine/calibration/forecast.py`):**
- Filter to nonzero coefficients
- Sort descending by |magnitude|
- Rank-percentile within sport: top 25% → "high"; bottom 25% → "low"; middle → "moderate"
- Return only the qualitative bucket

**Test guard (`apps/api/tests/test_forecast_endpoint.py`):**
```python
assert "model_coefficients" not in PremiumDetail.model_fields
```

**Pattern #8 extension (`b1_2b_2c_arc_patterns.md`):** "Paywall doesn't protect IP. If exposing data would enable reverse engineering, the data must not be exposed at any tier."

## Original Phase 3.3.4 ship (pre-3.3.4b)

The discussion below documents the original ship that was revised before
launch. The original 4-option preview composite at
`docs/audits/modeldetails_options_preview_2026-05-30/composite_full.png`
also still uses the original schema in its sample data; updated 3.3.4b
in this turn to use factor-impact labels (preserving the comparison's
visual shape).

---

## Decision context

Phase 3.3.4 surfaced a misframing: my earlier "premium dashboard drawer"
framing was incorrect — Spec 5 explicitly says "Model Details toggle/drawer
**on the game card**" (per-game UI, not dashboard). The
`/internal/modeldetails-options-preview` 4-section preview rendered
Options 1-4 on actual PrepRank surfaces with shared sample data. Reese
selected **Option 2 — GameCard per-card expand** based on the visual
comparison, after the external-product UX references (Baseball Savant,
Linear Peek, etc.) proved less informative than the PrepRank-rendered
mockups.

Composite for the 4-option decision-support preview lives at
`docs/audits/modeldetails_options_preview_2026-05-30/composite_full.png`
and per-section captures.

## What shipped

**New component:** `apps/web/src/components/ModelDetailsExpand.tsx`
- Renders the API `premium_detail` payload: β coefficients table,
  home/away typical-decile cards, predicted-decile reliability stats
  (n, gap, predicted, observed), methodology kebab-case deep-link
- Pure presentational; no state
- `role="region"`, `aria-labelledby` pointing to the toggle button

**Refactored:** `apps/web/src/components/GameCard.tsx`
- Now `"use client"` (toggle requires interactivity; existing consumers
  scores/teams/admin-replay are already client components, no SSR
  regression)
- Restructured from `<Link>` wrapping everything to `<article>` wrapping
  Link + a separate post-Link region for the toggle and expand panel
  (valid HTML — avoids button-inside-anchor)
- New optional props:
  - `isPremium?: boolean` — gates toggle visibility (defense in depth
    with API-side `premium_detail: null` for non-premium)
  - `isExpanded?: boolean` — parent-controlled for single-expand-only
  - `onToggleExpand?: () => void` — parent toggles
- Toggle visibility: `isPremium AND forecast.premium_detail AND !isFinal`
- Non-breaking: when consumers don't pass the new props, GameCard
  renders exactly as Phase 3.3.1 (no toggle, no panel)

## Two verifications (Reese 2026-05-30)

1. **Click target preservation** ✓
   - Clicking card body (inside `<Link>`) navigates to `/games/[id]` as before
   - Clicking toggle (separate `<button>` OUTSIDE the Link) expands inline; does NOT propagate to Link
   - Existing navigation paths from scores/teams/admin replay preserved
   - Button and link are siblings, not nested → valid HTML

2. **Premium chip treatment** ✓
   - Pre-commit swap: text-only chip → small pill matching tier-chip geometry
   - Pill background: `bg-steel-gray/20` (neutral, not crimson)
   - Pill text: `text-silver-print` uppercase tracking-wide
   - Smaller than tier chip (`text-[0.6rem]` and `px-1.5 py-0.5`) — secondary signal, not the primary chip on the card

## 6 build considerations addressed

| # | Consideration | Implementation |
|---|---|---|
| 1 | Vertical asymmetry | `items-start` on grid + `self-start` on article — organic asymmetry (adjacent cards stay natural height when one expands) |
| 2 | Toggle treatment | Subtle silver-print `▸`/`▾` + uppercase "Model Details" label; hover transitions to white. Neutral premium pill chip on the right |
| 3 | Single-expand-only | Parent holds `expandedId` state; per-card `onToggleExpand` calls `setExpandedId(prev => prev === id ? null : id)`. Clicking a second card auto-closes the first |
| 4 | Card width constraint | Verified at 3-col `lg:grid-cols-3` (scores.tsx narrowest, ~310px card width). β labels truncate via `truncate pr-2`; reliability stats keep 4-col grid; decile chips 2-col |
| 5 | Methodology deep-link convention | Kebab-case locked. Sample uses `/methodology#football-d6`. Engine already ships kebab-case (`forecast.py:225`); 3.3.5 anchors must match |
| 6 | ARIA accessibility | Button: `id`, `aria-expanded={isExpanded}`, `aria-controls={panelId}`. Panel: `id={panelId}`, `role="region"`, `aria-labelledby={toggleId}`. Keyboard: native `<button>` handles Enter/Space; tab order through siblings: card link → toggle → (if expanded) methodology link → next card |

## 7-state preview (composite.png)

| State | Verifies |
|---|---|
| 1 · Premium 2-col · none expanded | Closed toggle on each of 4 cards; subtle, doesn't disrupt scan |
| 2 · Premium 2-col · card #1 expanded | Full Model Details panel; adjacent card stays natural height |
| 3 · Premium 2-col · card #3 expanded | State transition demonstrates single-expand-only |
| 4 · Premium 3-col (scores.tsx narrowest) · card #2 expanded | Content fits at ~310px constraint |
| 5 · Premium single-column (mobile) · card #1 expanded | Full-width card; content breathes |
| 6 · Non-premium · no toggle | UI-side gate confirms; API also returns null (defense in depth) |
| 7 · Premium · forecast unavailable · no toggle | Toggle hidden when premium_detail is null |

## Capture method

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars \
  --window-size=1280,6400 \
  --screenshot=composite.png \
  http://localhost:3001/internal/gamecard-modeldetails-preview
```

## Cross-references

- `docs/audits/modeldetails_options_preview_2026-05-30/composite_full.png`
  — 4-option decision-support preview that surfaced Option 2 as the pick
- `claude-memory/apps/preprank/decisions.md` 2026-05-30 — Spec 5 surface
  correction + Option 2 selection + 6 considerations + 2 verifications
- `apps/web/src/components/ModelDetailsExpand.tsx` — new presentational
  component
- `apps/web/src/components/GameCard.tsx` — refactored to "use client"
  with optional premium props (non-breaking)
- `apps/web/src/app/internal/gamecard-modeldetails-preview/page.tsx` —
  preview route with 7 states + single-expand-only state machine
- `apps/api/app/auth/premium.py` `_is_premium()` — server-side premium
  gating (PREMIUM_TIERS check + non-expired subscription)
- `apps/api/app/routers/forecast.py` lines 180–243 — API-side
  `premium_detail: null` for non-premium (defense in depth)

## Phase 3.3.5 dependency (load-bearing)

The Model Details expand renders a methodology link in the form
`/methodology#football-d6` (kebab-case sport + d{decile+1}). Phase 3.3.5
methodology page MUST implement matching anchor IDs or this premium
feature ships with broken links. Anchor naming locked:

- `/methodology#football-d1` through `d10`
- `/methodology#boys-basketball-d1` through `d10`
- `/methodology#girls-basketball-d1` through `d10`
- `/methodology#boys-soccer-d1` through `d10`
- `/methodology#girls-soccer-d1` through `d10`
- `/methodology#baseball-d1` through `d10`
- `/methodology#softball-d1` through `d10`
- `/methodology#volleyball-d1` through `d10`

Total: 80 anchor IDs (8 sports × 10 deciles).
