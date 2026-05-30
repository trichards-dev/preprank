"use client";

import { useState } from "react";
import GameCard from "@/components/GameCard";
import type { Game, GameForecast } from "@/lib/api";

// Note: metadata cannot be exported from "use client" pages; SEO is unimportant
// for this internal preview. robots-noindex would normally live in a layout or
// server-component wrapper. For preview parity, the route is internal and
// won't be linked from anywhere in the nav.

function makeGame(overrides: Partial<Game>): Game {
  return {
    id: 1,
    home_team_id: 100,
    away_team_id: 200,
    sport_id: 1,
    season_year: 2025,
    game_date: "2025-10-17",
    week_number: 8,
    home_score: null,
    away_score: null,
    status: "scheduled",
    is_district: true,
    is_playoff: false,
    is_championship: false,
    is_out_of_state: false,
    home_team_name: "Brother Martin",
    away_team_name: "John Curtis",
    ...overrides,
  };
}

function makeForecast(overrides: Partial<GameForecast>): GameForecast {
  return {
    game_id: 1,
    sport: "Football",
    season_year: 2025,
    week_number: 8,
    status: "scheduled",
    home_team: { id: 100, name: "Brother Martin" },
    away_team: { id: 200, name: "John Curtis" },
    forecast: {
      home_win_probability: 58,
      home_win_probability_ci_low: 50,
      home_win_probability_ci_high: 66,
      confidence_tier: "lean",
      confidence_tier_label: "Lean",
    },
    forecast_unavailable_reason: null,
    source_data_caveat: null,
    premium_detail: {
      factor_contributions: [
        { label: "Opponent strength", impact: "high" },
        { label: "Home advantage", impact: "high" },
        { label: "Recent form", impact: "moderate" },
        { label: "Offensive/defensive balance", impact: "moderate" },
        { label: "Early-season carryover", impact: "low" },
      ],
      home_typical_decile: 7,
      away_typical_decile: 6,
      predicted_decile: 5,
      predicted_decile_reliability: {
        description: "Predictions in this range typically match observed outcomes within our confidence band.",
      },
      methodology_deep_link: "/methodology#football-d6",
    },
    calibration_run_id: "wf-phase6-calibration-kfold-tail-power-n139",
    computed_at: "2026-05-30T08:00:00Z",
    ...overrides,
  };
}

const FOUR_GAMES: Array<{ game: Game; forecast: GameForecast }> = [
  { game: makeGame({ id: 1, home_team_name: "Brother Martin", away_team_name: "John Curtis" }), forecast: makeForecast({ game_id: 1 }) },
  { game: makeGame({ id: 2, home_team_name: "Catholic - B.R.", away_team_name: "Jesuit" }), forecast: makeForecast({ game_id: 2 }) },
  { game: makeGame({ id: 3, home_team_name: "Acadiana", away_team_name: "Lafayette Christian" }), forecast: makeForecast({ game_id: 3 }) },
  { game: makeGame({ id: 4, home_team_name: "Many", away_team_name: "Notre Dame" }), forecast: makeForecast({ game_id: 4 }) },
];

const FORECAST_UNAVAILABLE: GameForecast = {
  ...makeForecast({}),
  game_id: 5,
  forecast: null,
  forecast_unavailable_reason: "RECENTLY_SCHEDULED",
  premium_detail: null,
};

function PremiumGrid({
  gridClass,
  initialExpandedId = null,
  caption,
}: {
  gridClass: string;
  initialExpandedId?: number | null;
  caption: string;
}) {
  const [expandedId, setExpandedId] = useState<number | null>(initialExpandedId);
  return (
    <div className="space-y-2">
      <div className="font-body text-xs uppercase tracking-wide text-silver-print">
        {caption}
      </div>
      <div className={`grid items-start ${gridClass}`}>
        {FOUR_GAMES.map(({ game, forecast }) => (
          <GameCard
            key={game.id}
            game={game}
            forecast={forecast}
            isPremium
            isExpanded={expandedId === game.id}
            onToggleExpand={() =>
              setExpandedId((prev) => (prev === game.id ? null : game.id))
            }
          />
        ))}
      </div>
    </div>
  );
}

function NonPremiumGrid() {
  return (
    <div className="space-y-2">
      <div className="font-body text-xs uppercase tracking-wide text-silver-print">
        Non-premium · no toggle on any card (UI gate confirms API-layer null defense)
      </div>
      <div className="grid items-start gap-4 md:grid-cols-2">
        {FOUR_GAMES.map(({ game, forecast }) => (
          <GameCard
            key={game.id}
            game={game}
            forecast={forecast}
            isPremium={false}
          />
        ))}
      </div>
    </div>
  );
}

function ForecastUnavailableCard() {
  const game = makeGame({
    id: 5,
    home_team_name: "Mt. Carmel",
    away_team_name: "South Beauregard",
  });
  return (
    <div className="space-y-2">
      <div className="font-body text-xs uppercase tracking-wide text-silver-print">
        Premium · forecast unavailable · no Model Details toggle (no premium_detail to expand)
      </div>
      <div className="grid items-start gap-4 md:grid-cols-2 max-w-3xl">
        <GameCard
          game={game}
          forecast={FORECAST_UNAVAILABLE}
          isPremium
          isExpanded={false}
          onToggleExpand={() => {}}
        />
      </div>
    </div>
  );
}

export default function GameCardModelDetailsPreviewPage() {
  return (
    <main className="min-h-screen bg-charcoal px-6 py-10">
      <div className="mx-auto max-w-7xl space-y-12">
        <header>
          <h1 className="font-display text-3xl font-bold text-white">
            GameCard + Model Details expand — Preview (Phase 3.3.4)
          </h1>
          <p className="mt-2 font-body text-sm text-silver-print max-w-3xl">
            Option 2 build: premium-conditional Model Details expand on
            GameCard. Single-expand-only at the grid container (clicking one
            closes others). Toggle subtle (silver-print ▸/▾), non-premium users
            see no toggle. Verified at 2-col, 3-col (scores.tsx narrowest), and
            single-column mobile widths.
          </p>
        </header>

        <section className="space-y-4">
          <div className="border-l-2 border-crimson pl-3">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide text-white">
              State 1 · Premium · 2-col grid · none expanded
            </h2>
          </div>
          <PremiumGrid
            gridClass="gap-4 md:grid-cols-2"
            initialExpandedId={null}
            caption="All 4 cards show closed toggle. Reading flow undisturbed for users who don't expand."
          />
        </section>

        <section className="space-y-4">
          <div className="border-l-2 border-crimson pl-3">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide text-white">
              State 2 · Premium · 2-col grid · card #1 expanded
            </h2>
          </div>
          <PremiumGrid
            gridClass="gap-4 md:grid-cols-2"
            initialExpandedId={1}
            caption="Card #1 (Brother Martin vs John Curtis) expanded. items-start on grid → adjacent card #2 stays its natural height. Organic asymmetry."
          />
        </section>

        <section className="space-y-4">
          <div className="border-l-2 border-crimson pl-3">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide text-white">
              State 3 · Premium · 2-col grid · card #3 expanded
            </h2>
          </div>
          <PremiumGrid
            gridClass="gap-4 md:grid-cols-2"
            initialExpandedId={3}
            caption="Clicking card #3 closes any other expanded card (single-expand-only). Demonstrates state transition vs State 2 above."
          />
        </section>

        <section className="space-y-4">
          <div className="border-l-2 border-crimson pl-3">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide text-white">
              State 4 · Premium · 3-col grid (scores.tsx narrowest) · card #2 expanded
            </h2>
          </div>
          <PremiumGrid
            gridClass="gap-3 md:grid-cols-2 lg:grid-cols-3"
            initialExpandedId={2}
            caption="Content fits at ~310px card width (lg:grid-cols-3 narrowest constraint). β coefficients truncate cleanly; decile chips stack; reliability stats stay in 4-col layout."
          />
        </section>

        <section className="space-y-4">
          <div className="border-l-2 border-crimson pl-3">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide text-white">
              State 5 · Premium · single-column (mobile) · card #1 expanded
            </h2>
          </div>
          <div className="mx-auto max-w-sm">
            <PremiumGrid
              gridClass="gap-4"
              initialExpandedId={1}
              caption="Single-column at mobile width (constrained to max-w-sm). Full-width card; no asymmetry concern; content has plenty of breathing room."
            />
          </div>
        </section>

        <section className="space-y-4">
          <div className="border-l-2 border-crimson pl-3">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide text-white">
              State 6 · Non-premium · no toggle visible
            </h2>
          </div>
          <NonPremiumGrid />
        </section>

        <section className="space-y-4">
          <div className="border-l-2 border-crimson pl-3">
            <h2 className="font-display text-xl font-bold uppercase tracking-wide text-white">
              State 7 · Premium · forecast unavailable · no toggle (defense in depth)
            </h2>
          </div>
          <ForecastUnavailableCard />
        </section>

        <footer className="border-t border-steel-gray/20 pt-6 font-body text-xs text-silver-print">
          Internal route. Not in nav. Defense-in-depth toggle gate:
          isPremium AND forecast.premium_detail AND not isFinal. API also
          returns premium_detail: null for non-premium (verified in 3.3.4
          audit). ARIA: button has aria-expanded + aria-controls; panel has
          role=region + aria-labelledby pointing to the toggle.
        </footer>
      </div>
    </main>
  );
}
