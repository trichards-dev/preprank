import type { Metadata } from "next";
import PostPickRevealCard from "@/components/PostPickRevealCard";
import type {
  PickemGame,
  GameForecast,
  ForecastBlock,
  ForecastUnavailableReason,
  SourceDataCaveat,
} from "@/lib/api";

export const metadata: Metadata = {
  title: "PostPickReveal Preview — Internal",
  robots: { index: false, follow: false },
};

function makeGame(overrides: Partial<PickemGame>): PickemGame {
  return {
    game_id: 1,
    home_team_id: 100,
    away_team_id: 200,
    home_team_name: "Brother Martin",
    away_team_name: "John Curtis",
    game_date: "2025-10-17",
    home_score: null,
    away_score: null,
    status: "scheduled",
    ...overrides,
  };
}

function makeForecast(
  overrides: Partial<GameForecast>,
  block?: ForecastBlock,
  reason?: ForecastUnavailableReason,
  caveat?: SourceDataCaveat,
): GameForecast {
  return {
    game_id: 1,
    sport: "Football",
    season_year: 2025,
    week_number: 8,
    status: "scheduled",
    home_team: { id: 100, name: "Brother Martin" },
    away_team: { id: 200, name: "John Curtis" },
    forecast: block ?? null,
    forecast_unavailable_reason: reason ?? null,
    source_data_caveat: caveat ?? null,
    premium_detail: null,
    calibration_run_id: "wf-phase6-calibration-kfold-tail-power-n139",
    computed_at: "2026-05-30T08:00:00Z",
    ...overrides,
  };
}

interface PreviewCase {
  caption: string;
  description: string;
  game: PickemGame;
  pickedTeamId: number;
  pickedTeamName: string;
  forecast: GameForecast | null;
}

const CASES: PreviewCase[] = [
  {
    caption: "1 · Confident pick · user AGREED",
    description: "User picked home; model also predicts home (89%). Agreement chip in crimson tint.",
    game: makeGame({
      home_team_name: "North Caddo",
      away_team_name: "Airline",
      home_team_id: 110,
      away_team_id: 210,
    }),
    pickedTeamId: 110,
    pickedTeamName: "North Caddo",
    forecast: makeForecast(
      { home_team: { id: 110, name: "North Caddo" }, away_team: { id: 210, name: "Airline" } },
      {
        home_win_probability: 89,
        home_win_probability_ci_low: 86,
        home_win_probability_ci_high: 92,
        confidence_tier: "confident_pick",
        confidence_tier_label: "Confident pick",
      },
    ),
  },
  {
    caption: "2 · Confident pick · user DISAGREED",
    description: "User picked the underdog away team; model strongly favors home. Disagreement chip in steel-gray.",
    game: makeGame({
      home_team_name: "North Caddo",
      away_team_name: "Airline",
      home_team_id: 110,
      away_team_id: 210,
    }),
    pickedTeamId: 210,
    pickedTeamName: "Airline",
    forecast: makeForecast(
      { home_team: { id: 110, name: "North Caddo" }, away_team: { id: 210, name: "Airline" } },
      {
        home_win_probability: 89,
        home_win_probability_ci_low: 86,
        home_win_probability_ci_high: 92,
        confidence_tier: "confident_pick",
        confidence_tier_label: "Confident pick",
      },
    ),
  },
  {
    caption: "3 · Lean · user AGREED",
    description: "Mid-confidence pick; user and model both favor home.",
    game: makeGame({
      home_team_name: "Brother Martin",
      away_team_name: "John Curtis",
      home_team_id: 120,
      away_team_id: 220,
    }),
    pickedTeamId: 120,
    pickedTeamName: "Brother Martin",
    forecast: makeForecast(
      { home_team: { id: 120, name: "Brother Martin" }, away_team: { id: 220, name: "John Curtis" } },
      {
        home_win_probability: 58,
        home_win_probability_ci_low: 50,
        home_win_probability_ci_high: 66,
        confidence_tier: "lean",
        confidence_tier_label: "Lean",
      },
    ),
  },
  {
    caption: "4 · Lean · user DISAGREED",
    description: "Mid-confidence model call; user took the other side. Disagreement here is more user-defensible.",
    game: makeGame({
      home_team_name: "Brother Martin",
      away_team_name: "John Curtis",
      home_team_id: 120,
      away_team_id: 220,
    }),
    pickedTeamId: 220,
    pickedTeamName: "John Curtis",
    forecast: makeForecast(
      { home_team: { id: 120, name: "Brother Martin" }, away_team: { id: 220, name: "John Curtis" } },
      {
        home_win_probability: 58,
        home_win_probability_ci_low: 50,
        home_win_probability_ci_high: 66,
        confidence_tier: "lean",
        confidence_tier_label: "Lean",
      },
    ),
  },
  {
    caption: "5 · Long shot · user AGREED",
    description: "User picked the away heavy favorite; model agrees (92% away). Wide CI band visible in PREPRANK PREDICTS card.",
    game: makeGame({
      home_team_name: "Bonnabel",
      away_team_name: "Sophie B. Wright",
      home_team_id: 130,
      away_team_id: 230,
    }),
    pickedTeamId: 230,
    pickedTeamName: "Sophie B. Wright",
    forecast: makeForecast(
      { home_team: { id: 130, name: "Bonnabel" }, away_team: { id: 230, name: "Sophie B. Wright" } },
      {
        home_win_probability: 8,
        home_win_probability_ci_low: 0,
        home_win_probability_ci_high: 25,
        confidence_tier: "long_shot",
        confidence_tier_label: "Long shot",
      },
    ),
  },
  {
    caption: "6 · Long shot · user DISAGREED",
    description: "User took the home underdog against a long-shot model call. The wide CI band frames the disagreement honestly — model is not confident either.",
    game: makeGame({
      home_team_name: "Bonnabel",
      away_team_name: "Sophie B. Wright",
      home_team_id: 130,
      away_team_id: 230,
    }),
    pickedTeamId: 130,
    pickedTeamName: "Bonnabel",
    forecast: makeForecast(
      { home_team: { id: 130, name: "Bonnabel" }, away_team: { id: 230, name: "Sophie B. Wright" } },
      {
        home_win_probability: 8,
        home_win_probability_ci_low: 0,
        home_win_probability_ci_high: 25,
        confidence_tier: "long_shot",
        confidence_tier_label: "Long shot",
      },
    ),
  },
  {
    caption: "7 · Forecast unavailable — no agreement chip",
    description: "Cannot assess agreement when the model has no prediction; agreement indicator is hidden, PREPRANK PREDICTS card shows subtle ? indicator.",
    game: makeGame({
      home_team_name: "Mt. Carmel",
      away_team_name: "South Beauregard",
      home_team_id: 140,
      away_team_id: 240,
    }),
    pickedTeamId: 140,
    pickedTeamName: "Mt. Carmel",
    forecast: makeForecast(
      {
        home_team: { id: 140, name: "Mt. Carmel" },
        away_team: { id: 240, name: "South Beauregard" },
      },
      undefined,
      "RECENTLY_SCHEDULED",
    ),
  },
  {
    caption: "8 · Baseball Lean with source-data caveat",
    description: "Spec 1a caveat flows through PREPRANK PREDICTS card; agreement chip rendered normally.",
    game: makeGame({
      home_team_name: "Parkview Baptist",
      away_team_name: "Opelousas Catholic",
      home_team_id: 150,
      away_team_id: 250,
      game_date: "2025-04-12",
    }),
    pickedTeamId: 150,
    pickedTeamName: "Parkview Baptist",
    forecast: makeForecast(
      {
        home_team: { id: 150, name: "Parkview Baptist" },
        away_team: { id: 250, name: "Opelousas Catholic" },
        sport: "Baseball",
      },
      {
        home_win_probability: 72,
        home_win_probability_ci_low: 64,
        home_win_probability_ci_high: 80,
        confidence_tier: "lean",
        confidence_tier_label: "Lean",
      },
      undefined,
      {
        code: "baseball_winner_first",
        prose:
          "Margin estimates for Baseball games carry additional uncertainty due to LHSAA source-page recording conventions.",
      },
    ),
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
      <PostPickRevealCard
        game={spec.game}
        pickedTeamId={spec.pickedTeamId}
        pickedTeamName={spec.pickedTeamName}
        forecast={spec.forecast}
      />
    </div>
  );
}

export default function PostPickRevealPreviewPage() {
  return (
    <main className="min-h-screen bg-charcoal px-6 py-10">
      <div className="mx-auto max-w-6xl space-y-10">
        <header>
          <h1 className="font-display text-3xl font-bold text-white">
            PostPickRevealCard — Preview (Phase 3.3.3)
          </h1>
          <p className="mt-2 font-body text-sm text-silver-print">
            Phase 3.3.3 surface integration. Pick&apos;em page enters a
            three-state grid: <code>isOpen → PickemCard</code> (pre-pick
            UX unchanged) / <code>!isOpen && !isScored → PostPickRevealCard</code>
            (this reveal) / <code>isScored → PickemCard with verdict</code>.
            Side-by-side YOUR PICK + PREPRANK PREDICTS layout with
            agreement indicator. Spec 4 (UI) ships v1.0; Spec 3.5
            backend agreement-rate telemetry decoupled to v1.1.
          </p>
        </header>

        {CASES.map((spec) => (
          <PreviewCell key={spec.caption} spec={spec} />
        ))}

        <footer className="border-t border-steel-gray/20 pt-6 font-body text-xs text-silver-print">
          Internal route. Not in nav. Not indexed. Sample data hard-coded
          for reproducibility. Halt-gate before Phase 3.3.4 (premium drawer).
        </footer>
      </div>
    </main>
  );
}
