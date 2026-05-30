import type { Metadata } from "next";
import WinProbabilityWithCI from "@/components/WinProbabilityWithCI";
import type { ForecastBlock, ForecastUnavailableReason, SourceDataCaveat } from "@/lib/api";

export const metadata: Metadata = {
  title: "GameDetail Preview — Internal",
  robots: { index: false, follow: false },
};

interface DetailCase {
  caption: string;
  description: string;
  homeTeamName: string;
  awayTeamName: string;
  meta: string;
  isFinal: boolean;
  homeScore: number | null;
  awayScore: number | null;
  forecast: ForecastBlock | null;
  forecastUnavailableReason?: ForecastUnavailableReason | null;
  sourceDataCaveat?: SourceDataCaveat | null;
  hasImpact?: boolean;
}

const CASES: DetailCase[] = [
  {
    caption: "1 · Scheduled + Lean forecast + impact table",
    description: "Reading order: header → scoreboard → WIN PROBABILITY (expanded variant) → WHAT'S AT STAKE table. Forecast and impact are complementary (pre-outcome prediction vs. conditional downstream impact).",
    homeTeamName: "Brother Martin",
    awayTeamName: "John Curtis",
    meta: "District · Week 8 · Friday, October 17, 2025",
    isFinal: false,
    homeScore: null,
    awayScore: null,
    forecast: {
      home_win_probability: 58,
      home_win_probability_ci_low: 50,
      home_win_probability_ci_high: 66,
      confidence_tier: "lean",
      confidence_tier_label: "Lean",
    },
    hasImpact: true,
  },
  {
    caption: "2 · Scheduled + Confident pick (no impact data)",
    description: "Forecast section renders even when impact table is empty. Heavy favorite case.",
    homeTeamName: "North Caddo",
    awayTeamName: "Airline",
    meta: "Non-District · Week 5 · Friday, September 19, 2025",
    isFinal: false,
    homeScore: null,
    awayScore: null,
    forecast: {
      home_win_probability: 89,
      home_win_probability_ci_low: 86,
      home_win_probability_ci_high: 92,
      confidence_tier: "confident_pick",
      confidence_tier_label: "Confident pick",
    },
    hasImpact: false,
  },
  {
    caption: "3 · Scheduled + forecast unavailable",
    description: "Subtle indicator preserved at expanded scale. Existing detail-page behavior intact (no regression).",
    homeTeamName: "Mt. Carmel",
    awayTeamName: "South Beauregard",
    meta: "Non-District · Friday, October 24, 2025",
    isFinal: false,
    homeScore: null,
    awayScore: null,
    forecast: null,
    forecastUnavailableReason: "RECENTLY_SCHEDULED",
    hasImpact: false,
  },
  {
    caption: "4 · Scheduled + Baseball + source-data caveat",
    description: "Caveat block displays at expanded scale below the tier chip + explicit CI range.",
    homeTeamName: "Parkview Baptist",
    awayTeamName: "Opelousas Catholic",
    meta: "District · Saturday, April 12, 2025",
    isFinal: false,
    homeScore: null,
    awayScore: null,
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
    hasImpact: false,
  },
  {
    caption: "5 · Final game — forecast section suppressed",
    description: "Consistent with GameCard behavior (Phase 3.3.1). v1.0 keeps post-game UX clean; Impact Analysis still shows.",
    homeTeamName: "Catholic - P.C.",
    awayTeamName: "Northlake Christian",
    meta: "Playoff · Saturday, December 6, 2025",
    isFinal: true,
    homeScore: 35,
    awayScore: 21,
    forecast: {
      home_win_probability: 65,
      home_win_probability_ci_low: 61,
      home_win_probability_ci_high: 69,
      confidence_tier: "confident_pick",
      confidence_tier_label: "Confident pick",
    },
    hasImpact: true,
  },
];

function DetailMock({ spec }: { spec: DetailCase }) {
  const { homeTeamName, awayTeamName, meta, isFinal, homeScore, awayScore } = spec;
  const homeWon = isFinal && homeScore !== null && awayScore !== null && homeScore > awayScore;
  const awayWon = isFinal && homeScore !== null && awayScore !== null && awayScore > homeScore;

  return (
    <section className="space-y-3">
      <div className="space-y-1">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">
          {spec.caption}
        </div>
        <div className="font-body text-xs text-silver-print/80">
          {spec.description}
        </div>
      </div>

      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-steel-gray uppercase tracking-wide">{meta}</span>
          <span className="text-xs text-steel-gray">(share)</span>
        </div>

        {/* Score card */}
        <div className="rounded-lg border border-steel-gray/30 p-6 mb-6">
          <div className="text-center mb-1">
            <span className={`text-xs font-bold uppercase ${isFinal ? "text-steel-gray" : "text-green-500"}`}>
              {isFinal ? "final" : "scheduled"}
            </span>
          </div>
          <div className="flex items-center justify-center gap-8 md:gap-16">
            <div className="text-center flex-1">
              <div className="text-xl md:text-2xl font-bold font-display">{homeTeamName}</div>
              <div className="text-xs text-steel-gray mt-1">HOME</div>
              <div className={`text-5xl md:text-6xl font-bold mt-2 font-display ${homeWon ? "text-white" : "text-steel-gray"}`}>
                {homeScore ?? "-"}
              </div>
            </div>
            <div className="text-3xl text-steel-gray font-bold">VS</div>
            <div className="text-center flex-1">
              <div className="text-xl md:text-2xl font-bold font-display">{awayTeamName}</div>
              <div className="text-xs text-steel-gray mt-1">AWAY</div>
              <div className={`text-5xl md:text-6xl font-bold mt-2 font-display ${awayWon ? "text-white" : "text-steel-gray"}`}>
                {awayScore ?? "-"}
              </div>
            </div>
          </div>
        </div>

        {/* Forecast section (Phase 3.3.2) — suppressed on finals */}
        {!isFinal && (spec.forecast !== undefined) && (
          <section className="mb-6">
            <h2 className="text-xl font-bold mb-4 font-display">WIN PROBABILITY</h2>
            <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-6">
              <WinProbabilityWithCI
                homeTeamName={homeTeamName}
                awayTeamName={awayTeamName}
                forecast={spec.forecast}
                forecastUnavailableReason={spec.forecastUnavailableReason}
                sourceDataCaveat={spec.sourceDataCaveat}
                variant="expanded"
              />
            </div>
          </section>
        )}

        {/* Impact placeholder */}
        {spec.hasImpact && (
          <section>
            <h2 className="text-xl font-bold mb-4 font-display">WHAT&apos;S AT STAKE</h2>
            <div className="rounded-lg border border-steel-gray/20 p-4 font-body text-sm text-silver-print">
              [Impact analysis table — rating / rank / playoff% conditional on each outcome]
            </div>
          </section>
        )}
      </div>
    </section>
  );
}

export default function GameDetailPreviewPage() {
  return (
    <main className="min-h-screen bg-charcoal px-6 py-10">
      <div className="mx-auto max-w-6xl space-y-12">
        <header>
          <h1 className="font-display text-3xl font-bold text-white">
            GameDetail + WIN PROBABILITY section — Preview (Phase 3.3.2)
          </h1>
          <p className="mt-2 font-body text-sm text-silver-print">
            Phase 3.3.2 surface integration: <code>/games/[id]</code> gains a
            WIN PROBABILITY section between the scoreboard and Impact Analysis. Uses
            <code>variant=&quot;expanded&quot;</code> (taller bar, explicit CI
            numerals). Final games suppress the section consistent with
            GameCard Phase 3.3.1 behavior.
          </p>
        </header>

        {CASES.map((spec) => (
          <DetailMock key={spec.caption} spec={spec} />
        ))}

        <footer className="border-t border-steel-gray/20 pt-6 font-body text-xs text-silver-print">
          Internal route. Not in nav. Not indexed. Scoreboard + impact-placeholder
          mocks production-realistic context without hitting the DB; the actual
          /games/[id] page wires the same WIN PROBABILITY section to live data via
          fetchGameForecast(gameId) in the page useEffect.
        </footer>
      </div>
    </main>
  );
}
