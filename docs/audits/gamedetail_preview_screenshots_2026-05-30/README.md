# GameDetail + WIN PROBABILITY section — Phase 3.3.2 audit

**Captured:** 2026-05-30
**Approved by:** Reese Richards (with heading rename to WIN PROBABILITY)
**Verdict:** Clean integration. Read-gate scenario (1) confirmed; no remove/replace needed.

## Read-gate findings (pre-implementation)

Per the 3.3.2 read-gate discipline, audited
`apps/web/src/app/games/[id]/page.tsx` BEFORE implementation:

| Lines | Content | Prediction-related? |
|---|---|---|
| 43–54 | Game header (type · week · date + ShareButton) | No |
| 56–92 | Score card (status badge + team names + VS + scores) | No |
| 94–132 | "WHAT'S AT STAKE" Impact Analysis table | Yes, but **orthogonal** to win-probability |

The Impact Analysis table shows **conditional outcomes** for affected
teams ("Rating if home wins / if away wins", "Rank if home / if
away", "Playoff% if home / if away"). It is downstream impact —
conditional on each outcome, what happens to other teams in the
rankings. It is NOT a per-game win-probability prediction. The two
concepts are complementary:

- WinProbabilityWithCI answers: *"How likely is home to win?"* — pre-outcome
- Impact Analysis answers: *"Conditional on each outcome, what changes downstream?"*

**Classification: Scenario (1) — no pre-existing prediction content; clean add.** No
remove/replace decision required.

## Heading rename: FORECAST → WIN PROBABILITY

Initial draft used "FORECAST" as the section heading. Reese flagged
this on visual review and recommended WIN PROBABILITY for brand-voice
consistency with the existing "PLAYOFF PROBABILITY" pattern from the
brand spec ("WHAT'S AT STAKE 76% PLAYOFF PROBABILITY ↑12% THIS WEEK").

Three reasons:
1. Same noun construction + declarative register as PLAYOFF PROBABILITY
2. More specific than FORECAST (which reads weather-app)
3. Lexicon anchoring — uses vocabulary the brand already established

Applied before commit.

## Implementation

Inserted between line 92 (score card close) and line 94 (Impact
Analysis open) on `apps/web/src/app/games/[id]/page.tsx`:

```tsx
{/* Win Probability (Phase 3.3.2) */}
{!isFinal && forecast && (
  <section className="mb-8">
    <h2 className="text-xl font-bold mb-4" style={{ fontFamily: "var(--font-display)" }}>
      WIN PROBABILITY
    </h2>
    <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-6">
      <WinProbabilityWithCI
        homeTeamName={...}
        awayTeamName={...}
        forecast={forecast.forecast}
        forecastUnavailableReason={forecast.forecast_unavailable_reason}
        sourceDataCaveat={forecast.source_data_caveat}
        variant="expanded"
      />
    </div>
  </section>
)}
```

- Final games: section suppressed (consistent with GameCard Phase 3.3.1 behavior; v1.0 keeps post-game UX clean)
- Forecast fetch failures: section omitted, page unchanged (`.catch(() => null)` on fetchGameForecast inside Promise.all)
- `hideTeamNames` left at default `false` — detail page does NOT have its own scoreboard rows below the WIN PROBABILITY section, so the component carries labels via the bigger bar + explicit CI numerals + plain-language secondary line per the design doc mockup

## Composite (5 cases)

| # | State | Verifies |
|---|---|---|
| 1 | Scheduled · Lean · impact table | Reading flow: header → scoreboard → WIN PROBABILITY → WHAT'S AT STAKE |
| 2 | Scheduled · Confident pick · no impact | Section renders standalone; band is a thin sliver near 89% |
| 3 | Scheduled · forecast unavailable | Subtle "? vs ?" indicator at expanded scale; no UI hole |
| 4 | Scheduled · Baseball + source-data caveat | ⓘ prose displays below CI numerals; Spec 1a preserved |
| 5 | Final game (35-21) | WIN PROBABILITY section SUPPRESSED; scoreboard + impact intact |

## Capture method

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars \
  --window-size=1280,4200 \
  --screenshot=composite.png \
  http://localhost:3001/internal/gamedetail-preview
```

## Cross-references

- `claude-memory/apps/preprank/decisions.md` 2026-05-30 — Phase 3.3.2
  ship + read-gate scenario (1) classification
- `apps/web/src/app/games/[id]/page.tsx` — WIN PROBABILITY section
  inserted between score card and Impact Analysis
- `apps/web/src/app/internal/gamedetail-preview/page.tsx` — 5-state
  preview with stable hard-coded sample data
- `docs/audits/gamecard_preview_screenshots_2026-05-30/README.md` —
  Phase 3.3.1 ship; consistent finals-suppression behavior
