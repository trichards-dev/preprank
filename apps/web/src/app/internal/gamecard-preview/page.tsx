import type { Metadata } from "next";
import GameCard from "@/components/GameCard";
import type { Game, GameForecast } from "@/lib/api";

export const metadata: Metadata = {
  title: "GameCard Preview — Internal",
  robots: { index: false, follow: false },
};

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
    home_team_name: "North Caddo",
    away_team_name: "Airline",
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
    home_team: { id: 100, name: "North Caddo" },
    away_team: { id: 200, name: "Airline" },
    forecast: null,
    forecast_unavailable_reason: null,
    source_data_caveat: null,
    premium_detail: null,
    calibration_run_id: "wf-phase6-calibration-kfold-tail-power-n139",
    computed_at: "2026-05-30T08:00:00Z",
    ...overrides,
  };
}

interface PreviewCase {
  caption: string;
  description: string;
  game: Game;
  forecast?: GameForecast | null;
}

const CASES: PreviewCase[] = [
  {
    caption: "1 · Scheduled + Confident pick",
    description: "Routine case: scheduled district football, calibrated forecast available, narrow CI.",
    game: makeGame({
      id: 1,
      home_team_name: "North Caddo",
      away_team_name: "Airline",
    }),
    forecast: makeForecast({
      forecast: {
        home_win_probability: 89,
        home_win_probability_ci_low: 86,
        home_win_probability_ci_high: 92,
        confidence_tier: "confident_pick",
        confidence_tier_label: "Confident pick",
      },
    }),
  },
  {
    caption: "2 · Scheduled + Lean",
    description: "Closer matchup; mid-range CI; tier chip reads Lean.",
    game: makeGame({
      id: 2,
      home_team_id: 101,
      away_team_id: 201,
      home_team_name: "Brother Martin",
      away_team_name: "John Curtis",
      is_district: false,
    }),
    forecast: makeForecast({
      game_id: 2,
      forecast: {
        home_win_probability: 58,
        home_win_probability_ci_low: 50,
        home_win_probability_ci_high: 66,
        confidence_tier: "lean",
        confidence_tier_label: "Lean",
      },
    }),
  },
  {
    caption: "3 · Scheduled + Long shot",
    description: "Heavy favorite with wide CI; band dominates the bar.",
    game: makeGame({
      id: 3,
      home_team_id: 102,
      away_team_id: 202,
      home_team_name: "Bonnabel",
      away_team_name: "Sophie B. Wright",
      is_playoff: true,
      is_district: false,
    }),
    forecast: makeForecast({
      game_id: 3,
      forecast: {
        home_win_probability: 8,
        home_win_probability_ci_low: 0,
        home_win_probability_ci_high: 25,
        confidence_tier: "long_shot",
        confidence_tier_label: "Long shot",
      },
    }),
  },
  {
    caption: "4 · Scheduled + forecast unavailable",
    description: "Game added recently; engine hasn't computed a forecast yet. Subtle indicator (Spec 7).",
    game: makeGame({
      id: 4,
      home_team_id: 103,
      away_team_id: 203,
      home_team_name: "Mt. Carmel",
      away_team_name: "South Beauregard",
      is_district: false,
    }),
    forecast: makeForecast({
      game_id: 4,
      forecast: null,
      forecast_unavailable_reason: "RECENTLY_SCHEDULED",
    }),
  },
  {
    caption: "5 · Scheduled + Baseball caveat",
    description: "Baseball game; Spec 1a source-data caveat displays below tier label.",
    game: makeGame({
      id: 5,
      home_team_id: 104,
      away_team_id: 204,
      home_team_name: "Parkview Baptist",
      away_team_name: "Opelousas Catholic",
      week_number: null,
      game_date: "2025-04-12",
    }),
    forecast: makeForecast({
      game_id: 5,
      sport: "Baseball",
      forecast: {
        home_win_probability: 72,
        home_win_probability_ci_low: 64,
        home_win_probability_ci_high: 80,
        confidence_tier: "lean",
        confidence_tier_label: "Lean",
      },
      source_data_caveat: {
        code: "baseball_winner_first",
        prose:
          "Margin estimates for Baseball games carry additional uncertainty due to LHSAA source-page recording conventions.",
      },
    }),
  },
  {
    caption: "6 · Final game (forecast suppressed)",
    description: "isFinal=true → forecast block hidden even when prop provided. v1.0 keeps post-game UX clean; v1.1 may revisit prediction-vs-actual.",
    game: makeGame({
      id: 6,
      home_team_id: 105,
      away_team_id: 205,
      home_team_name: "Catholic - P.C.",
      away_team_name: "Northlake Christian",
      status: "final",
      home_score: 35,
      away_score: 21,
    }),
    forecast: makeForecast({
      game_id: 6,
      status: "final",
      forecast: {
        home_win_probability: 65,
        home_win_probability_ci_low: 61,
        home_win_probability_ci_high: 69,
        confidence_tier: "confident_pick",
        confidence_tier_label: "Confident pick",
      },
    }),
  },
  {
    caption: "7 · Scheduled, NO forecast prop (legacy consumer)",
    description: "Existing pages that don't pass the optional forecast prop render exactly as before — non-breaking integration verified.",
    game: makeGame({
      id: 7,
      home_team_id: 106,
      away_team_id: 206,
      home_team_name: "Lutcher",
      away_team_name: "Berwick",
    }),
    forecast: undefined,
  },
];

function PreviewCell({ spec }: { spec: PreviewCase }) {
  return (
    <div className="space-y-2">
      <div className="space-y-1">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">
          {spec.caption}
        </div>
        <div className="font-body text-xs text-silver-print/80">
          {spec.description}
        </div>
      </div>
      <GameCard game={spec.game} forecast={spec.forecast} />
    </div>
  );
}

export default function GameCardPreviewPage() {
  return (
    <main className="min-h-screen bg-charcoal px-6 py-10">
      <div className="mx-auto max-w-6xl space-y-10">
        <header>
          <h1 className="font-display text-3xl font-bold text-white">
            GameCard + WinProbabilityWithCI — Preview (Phase 3.3.1)
          </h1>
          <p className="mt-2 font-body text-sm text-silver-print">
            Phase 3.3.1 visual review. GameCard.tsx now accepts an optional{" "}
            <code>forecast</code> prop; renders the WinProbabilityWithCI compact
            variant for scheduled games when supplied. Existing scoreboard /
            status / metadata rendering preserved (case 7 verifies legacy
            consumers still work).
          </p>
        </header>

        <section className="space-y-4">
          <h2 className="font-display text-xl font-semibold uppercase tracking-wide text-white">
            Forecast integration states
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {CASES.map((spec) => (
              <PreviewCell key={spec.caption} spec={spec} />
            ))}
          </div>
        </section>

        <footer className="border-t border-steel-gray/20 pt-6 font-body text-xs text-silver-print">
          Internal route. Not in nav. Not indexed. Sample data hard-coded for
          reproducibility. Halt-gate before Phase 3.3.2 (game detail expanded
          variant).
        </footer>
      </div>
    </main>
  );
}
