# WinProbabilityWithCI — Phase 3.2 visual-review artifact

**Captured:** 2026-05-30
**Approved by:** Reese Richards
**Verdict:** Spec anchoring verified across all 12 dimensions.

## What this is

The reference frame for "this is what spec-anchored looks like in v1.0".
Phase 3.2 visual-review halt-gate — captured before Phase 3.3 surface
integration was kicked off.

## Capture method

Headless Chrome (installed Chrome.app, not a transient install):

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars \
  --window-size=1280,2400 \
  --screenshot=composite.png \
  http://localhost:3001/internal/winprob-preview
```

Renders the preview route at full viewport height with stable hard-coded
sample data, so the artifact is reproducible without DB / API state.

## What the composite shows

Three sections, 10 states total:

**Compact variant** (game card primitive, 2-col grid)
- a · Confident pick — North Caddo vs Airline (89-11, hw 3pp)
- c · Lean — John Ehret vs Jefferson Rise Charter (44-56, hw 9pp)
- e · Toss-up — Lutcher vs Berwick (52-48, hw 13pp)
- g · Long shot — Bonnabel vs Sophie B. Wright (8-92, hw 17pp)

**Expanded variant** (game detail page, 2-col grid, taller bar + explicit CI numerals)
- b · Confident pick — North Caddo vs Airline
- d · Lean — Brother Martin vs John Curtis
- f · Toss-up — Lutcher vs Berwick
- h · Long shot — Bonnabel vs Sophie B. Wright

**Special states** (2-col grid)
- i · Forecast unavailable — Mt. Carmel vs South Beauregard (RECENTLY_SCHEDULED)
- j · Lean with Baseball source-data caveat — Parkview Baptist vs Opelousas Catholic

## Spec-anchoring verification (Reese 2026-05-30)

| Anchor | Verified |
|---|---|
| Crimson `#C22032` bar fill | ✓ |
| Charcoal `#1A1A1E` page bg | ✓ |
| Charcoal-elevated `#2A2A2E` card bg | ✓ |
| Steel-gray `#6B6B73` @ 40% confidence band overlay | ✓ |
| Silver-print `#9B9BA3` tier chip + small print | ✓ |
| Barlow Condensed probability % numerals | ✓ |
| Source Sans 3 body / chip text | ✓ |
| Sport Chip pill geometry reuse on tier chips | ✓ |
| PLAYOFF PROBABILITY bar visual rhythm | ✓ |
| Neutral tier chips (no R/Y/G; same steel-gray across all 4) | ✓ |
| "Long shot" final label (not placeholder) | ✓ |
| Sport-neutral tier chips (no sport-context theming) | ✓ |

**Load-bearing design verdict:** band-width-as-uncertainty mechanism IS
working. A→G progression from thin gray sliver to wide gray band dominating
the bar reads intuitively without statistical literacy required.

## Pre-existing observations (v1.1 polish backlog, not Phase 3.2 issues)

- Navbar wraps "Boys Basketball" / "Girls Basketball" / "Boys Soccer" /
  "Girls Soccer" to two lines at 1280px viewport. Visible in composite top
  band. Pre-existing; not caused by this component. Filed as v1.1 nav
  polish.

## Cross-references

- `claude-memory/apps/preprank/winprob_ci_component_design_2026-05-30.md`
  — Phase 3.1 approved design
- `claude-memory/apps/preprank/decisions.md` 2026-05-30 — brand-spec
  anchoring sign-off
- `apps/web/src/components/WinProbabilityWithCI.tsx` — the primitive
- `apps/web/src/app/internal/winprob-preview/page.tsx` — preview route
  source (sample data hard-coded for reproducibility)
