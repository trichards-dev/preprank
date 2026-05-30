import type { Metadata } from "next";
import WinProbabilityWithCI from "@/components/WinProbabilityWithCI";
import type {
  ForecastBlock,
  ForecastUnavailableReason,
  SourceDataCaveat,
} from "@/lib/api";

export const metadata: Metadata = {
  title: "WinProb Preview — Internal",
  robots: { index: false, follow: false },
};

interface CaseSpec {
  caption: string;
  homeTeamName: string;
  awayTeamName: string;
  forecast: ForecastBlock | null;
  forecastUnavailableReason?: ForecastUnavailableReason | null;
  sourceDataCaveat?: SourceDataCaveat | null;
  hideTeamNames?: boolean;
}

const COMPACT_CASES: CaseSpec[] = [
  {
    caption: "a · Confident pick (compact) — hw 3pp",
    homeTeamName: "North Caddo",
    awayTeamName: "Airline",
    forecast: {
      home_win_probability: 89,
      home_win_probability_ci_low: 86,
      home_win_probability_ci_high: 92,
      confidence_tier: "confident_pick",
      confidence_tier_label: "Confident pick",
    },
  },
  {
    caption: "c · Lean (compact) — hw 9pp",
    homeTeamName: "John Ehret",
    awayTeamName: "Jefferson Rise Charter",
    forecast: {
      home_win_probability: 44,
      home_win_probability_ci_low: 35,
      home_win_probability_ci_high: 53,
      confidence_tier: "lean",
      confidence_tier_label: "Lean",
    },
  },
  {
    caption: "e · Toss-up (compact) — hw 13pp",
    homeTeamName: "Lutcher",
    awayTeamName: "Berwick",
    forecast: {
      home_win_probability: 52,
      home_win_probability_ci_low: 39,
      home_win_probability_ci_high: 65,
      confidence_tier: "toss_up",
      confidence_tier_label: "Toss-up",
    },
  },
  {
    caption: "g · Long shot (compact) — hw 17pp",
    homeTeamName: "Bonnabel",
    awayTeamName: "Sophie B. Wright",
    forecast: {
      home_win_probability: 8,
      home_win_probability_ci_low: 0,
      home_win_probability_ci_high: 25,
      confidence_tier: "long_shot",
      confidence_tier_label: "Long shot",
    },
  },
];

const EXPANDED_CASES: CaseSpec[] = [
  {
    caption: "b · Confident pick (expanded)",
    homeTeamName: "North Caddo",
    awayTeamName: "Airline",
    forecast: {
      home_win_probability: 89,
      home_win_probability_ci_low: 86,
      home_win_probability_ci_high: 92,
      confidence_tier: "confident_pick",
      confidence_tier_label: "Confident pick",
    },
  },
  {
    caption: "d · Lean (expanded)",
    homeTeamName: "Brother Martin",
    awayTeamName: "John Curtis",
    forecast: {
      home_win_probability: 58,
      home_win_probability_ci_low: 50,
      home_win_probability_ci_high: 66,
      confidence_tier: "lean",
      confidence_tier_label: "Lean",
    },
  },
  {
    caption: "f · Toss-up (expanded)",
    homeTeamName: "Lutcher",
    awayTeamName: "Berwick",
    forecast: {
      home_win_probability: 52,
      home_win_probability_ci_low: 39,
      home_win_probability_ci_high: 65,
      confidence_tier: "toss_up",
      confidence_tier_label: "Toss-up",
    },
  },
  {
    caption: "h · Long shot (expanded)",
    homeTeamName: "Bonnabel",
    awayTeamName: "Sophie B. Wright",
    forecast: {
      home_win_probability: 8,
      home_win_probability_ci_low: 0,
      home_win_probability_ci_high: 25,
      confidence_tier: "long_shot",
      confidence_tier_label: "Long shot",
    },
  },
];

const HIDE_TEAM_NAME_CASES: CaseSpec[] = [
  {
    caption: "k · Confident pick (compact, hideTeamNames=true)",
    homeTeamName: "North Caddo",
    awayTeamName: "Airline",
    forecast: {
      home_win_probability: 89,
      home_win_probability_ci_low: 86,
      home_win_probability_ci_high: 92,
      confidence_tier: "confident_pick",
      confidence_tier_label: "Confident pick",
    },
    hideTeamNames: true,
  },
  {
    caption: "l · Lean (compact, hideTeamNames=true)",
    homeTeamName: "John Ehret",
    awayTeamName: "Jefferson Rise Charter",
    forecast: {
      home_win_probability: 44,
      home_win_probability_ci_low: 35,
      home_win_probability_ci_high: 53,
      confidence_tier: "lean",
      confidence_tier_label: "Lean",
    },
    hideTeamNames: true,
  },
];

const SPECIAL_CASES: CaseSpec[] = [
  {
    caption: "i · Forecast unavailable (Recently scheduled)",
    homeTeamName: "Mt. Carmel",
    awayTeamName: "South Beauregard",
    forecast: null,
    forecastUnavailableReason: "RECENTLY_SCHEDULED",
  },
  {
    caption: "j · Lean (compact) with Baseball source-data caveat",
    homeTeamName: "Parkview Baptist",
    awayTeamName: "Opelousas Catholic",
    forecast: {
      home_win_probability: 72,
      home_win_probability_ci_low: 64,
      home_win_probability_ci_high: 80,
      confidence_tier: "lean",
      confidence_tier_label: "Lean",
    },
    sourceDataCaveat: {
      code: "baseball_winner_first",
      prose:
        "Margin estimates for Baseball games carry additional uncertainty due to LHSAA source-page recording conventions.",
    },
  },
];

function PreviewCard({
  spec,
  variant,
}: {
  spec: CaseSpec;
  variant: "compact" | "expanded";
}) {
  return (
    <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-4">
      <div className="mb-3 font-body text-xs uppercase tracking-wide text-silver-print">
        {spec.caption}
      </div>
      <WinProbabilityWithCI
        homeTeamName={spec.homeTeamName}
        awayTeamName={spec.awayTeamName}
        forecast={spec.forecast}
        forecastUnavailableReason={spec.forecastUnavailableReason}
        sourceDataCaveat={spec.sourceDataCaveat}
        variant={variant}
        hideTeamNames={spec.hideTeamNames}
      />
    </div>
  );
}

export default function WinProbPreviewPage() {
  return (
    <main className="min-h-screen bg-charcoal px-6 py-10">
      <div className="mx-auto max-w-6xl space-y-10">
        <header>
          <h1 className="font-display text-3xl font-bold text-white">
            &lt;WinProbabilityWithCI&gt; — Preview
          </h1>
          <p className="mt-2 font-body text-sm text-silver-print">
            Phase 3.2 visual review. Spec-anchored tokens (#C22032 crimson · #1A1A1E charcoal ·
            #2A2A2E elevated · #6B6B73 steel-gray · #9B9BA3 silver-print). Sport Chip pill
            geometry + PLAYOFF PROBABILITY bar rhythm inherited.
          </p>
        </header>

        <section className="space-y-4">
          <h2 className="font-display text-xl font-semibold uppercase tracking-wide text-white">
            Compact variant (game card primitive)
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {COMPACT_CASES.map((spec) => (
              <PreviewCard key={spec.caption} spec={spec} variant="compact" />
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="font-display text-xl font-semibold uppercase tracking-wide text-white">
            Expanded variant (game detail page)
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {EXPANDED_CASES.map((spec) => (
              <PreviewCard key={spec.caption} spec={spec} variant="expanded" />
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="font-display text-xl font-semibold uppercase tracking-wide text-white">
            hideTeamNames variant (used by GameCard nesting)
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {HIDE_TEAM_NAME_CASES.map((spec) => (
              <PreviewCard key={spec.caption} spec={spec} variant="compact" />
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="font-display text-xl font-semibold uppercase tracking-wide text-white">
            Special states
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {SPECIAL_CASES.map((spec) => (
              <PreviewCard key={spec.caption} spec={spec} variant="compact" />
            ))}
          </div>
        </section>

        <footer className="border-t border-steel-gray/20 pt-6 font-body text-xs text-silver-print">
          Internal route. Not in nav. Not indexed. Sample data per
          claude-memory/apps/preprank/winprob_ci_component_design_2026-05-30.md drift-test data.
        </footer>
      </div>
    </main>
  );
}
