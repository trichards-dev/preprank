import type { Metadata } from "next";
import Link from "next/link";
import WinProbabilityWithCI from "@/components/WinProbabilityWithCI";
import type { ForecastBlock } from "@/lib/api";

export const metadata: Metadata = {
  title: "Model Details — 4-option Preview · Internal",
  robots: { index: false, follow: false },
};

// --- Stable shared sample data (used by all 4 sections for fair comparison) ---

const SAMPLE_GAME = {
  homeTeamName: "Brother Martin",
  awayTeamName: "John Curtis",
  meta: "District · Week 8 · Friday, October 17, 2025",
  status: "scheduled" as const,
  homeScore: null as number | null,
  awayScore: null as number | null,
};

const SAMPLE_FORECAST: ForecastBlock = {
  home_win_probability: 58,
  home_win_probability_ci_low: 50,
  home_win_probability_ci_high: 66,
  confidence_tier: "lean",
  confidence_tier_label: "Lean",
};

interface PremiumDetailSample {
  factor_contributions: Array<{ label: string; impact: "high" | "moderate" | "low" }>;
  home_typical_decile: number;
  away_typical_decile: number;
  predicted_decile: number;          // 0-indexed
  predicted_decile_reliability: { description: string };
  methodology_deep_link: string;
  sport: string;
}

const SAMPLE_PREMIUM: PremiumDetailSample = {
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
  sport: "Football",
};

// --- Local ModelDetailsBlock helper — renders the API premium_detail payload ---
//
// This local component intentionally lives ONLY in the preview route. It is NOT
// committed to /components/ until Thomas signs off on a surface direction.

const IMPACT_CLASSES_PREVIEW: Record<"high" | "moderate" | "low", string> = {
  high: "bg-crimson/20 text-white",
  moderate: "bg-steel-gray/20 text-silver-print",
  low: "bg-steel-gray/10 text-silver-print",
};

function ModelDetailsBlock({ data }: { data: PremiumDetailSample }) {
  const reliability = data.predicted_decile_reliability;
  return (
    <div className="space-y-4 font-body">
      <div>
        <div className="font-display text-xs uppercase tracking-wide text-silver-print mb-1">
          What&apos;s driving this prediction · {data.sport}
        </div>
        <ul className="space-y-1">
          {data.factor_contributions.map((fc) => (
            <li
              key={fc.label}
              className="flex items-center justify-between gap-2 border-b border-steel-gray/15 py-1"
            >
              <span className="text-xs text-white">{fc.label}</span>
              <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wide whitespace-nowrap ${IMPACT_CLASSES_PREVIEW[fc.impact]}`}>
                {fc.impact} impact
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs">
        <div className="rounded border border-steel-gray/20 p-2">
          <div className="font-display uppercase tracking-wide text-silver-print">Home typical decile</div>
          <div className="mt-1 font-display text-xl text-white">D{data.home_typical_decile}</div>
        </div>
        <div className="rounded border border-steel-gray/20 p-2">
          <div className="font-display uppercase tracking-wide text-silver-print">Away typical decile</div>
          <div className="mt-1 font-display text-xl text-white">D{data.away_typical_decile}</div>
        </div>
      </div>

      <div className="rounded border border-steel-gray/20 p-2 text-xs">
        <div className="font-display uppercase tracking-wide text-silver-print">
          Predicted decile · D{data.predicted_decile + 1}
        </div>
        <div className="mt-1 text-silver-print">{reliability.description}</div>
      </div>

      <Link
        href={data.methodology_deep_link}
        className="inline-block text-xs text-crimson hover:underline font-body"
      >
        Read methodology for {data.sport} D{data.predicted_decile + 1} →
      </Link>
    </div>
  );
}

// --- Section A · Option 1 — Inline accordion on game detail page ---

function GameDetailMock({ children }: { children?: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-3xl">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-steel-gray uppercase tracking-wide">{SAMPLE_GAME.meta}</span>
      </div>
      <div className="rounded-lg border border-steel-gray/30 p-6 mb-6">
        <div className="text-center mb-1">
          <span className="text-xs font-bold uppercase text-green-500">scheduled</span>
        </div>
        <div className="flex items-center justify-center gap-8 md:gap-16">
          <div className="text-center flex-1">
            <div className="text-xl md:text-2xl font-bold font-display">{SAMPLE_GAME.homeTeamName}</div>
            <div className="text-xs text-steel-gray mt-1">HOME</div>
            <div className="text-5xl md:text-6xl font-bold mt-2 font-display text-steel-gray">-</div>
          </div>
          <div className="text-3xl text-steel-gray font-bold">VS</div>
          <div className="text-center flex-1">
            <div className="text-xl md:text-2xl font-bold font-display">{SAMPLE_GAME.awayTeamName}</div>
            <div className="text-xs text-steel-gray mt-1">AWAY</div>
            <div className="text-5xl md:text-6xl font-bold mt-2 font-display text-steel-gray">-</div>
          </div>
        </div>
      </div>
      <section className="mb-6">
        <h2 className="text-xl font-bold mb-4 font-display">WIN PROBABILITY</h2>
        <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-6">
          <WinProbabilityWithCI
            homeTeamName={SAMPLE_GAME.homeTeamName}
            awayTeamName={SAMPLE_GAME.awayTeamName}
            forecast={SAMPLE_FORECAST}
            variant="expanded"
          />
        </div>
      </section>
      {children}
      <section className="mb-2">
        <h2 className="text-xl font-bold mb-4 font-display">WHAT&apos;S AT STAKE</h2>
        <div className="rounded-lg border border-steel-gray/20 p-4 font-body text-sm text-silver-print">
          [Impact analysis table — rating / rank / playoff% conditional on each outcome]
        </div>
      </section>
    </div>
  );
}

function AccordionToggle({ open, children }: { open: boolean; children: React.ReactNode }) {
  return (
    <section className="mb-6">
      <details open={open} className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated">
        <summary className="cursor-pointer select-none p-4 list-none flex items-center justify-between">
          <span className="font-display text-base font-bold uppercase tracking-wide text-white">
            <span className="mr-2 text-silver-print">{open ? "▾" : "▸"}</span>
            Model Details
          </span>
          <span className="font-body text-xs uppercase tracking-wide text-silver-print">premium</span>
        </summary>
        <div className="p-4 pt-0">{children}</div>
      </details>
    </section>
  );
}

function SectionA() {
  return (
    <div className="space-y-10">
      <div className="space-y-2">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">A.1 · Premium · accordion closed</div>
        <GameDetailMock>
          <AccordionToggle open={false}>
            <ModelDetailsBlock data={SAMPLE_PREMIUM} />
          </AccordionToggle>
        </GameDetailMock>
      </div>
      <div className="space-y-2">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">A.2 · Premium · accordion expanded</div>
        <GameDetailMock>
          <AccordionToggle open={true}>
            <ModelDetailsBlock data={SAMPLE_PREMIUM} />
          </AccordionToggle>
        </GameDetailMock>
      </div>
      <div className="space-y-2">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">A.3 · Non-premium · accordion absent</div>
        <GameDetailMock />
      </div>
    </div>
  );
}

// --- Section B · Option 2 — GameCard per-card expand ---

function GameCardMock({ idx, expanded, premium }: { idx: number; expanded?: boolean; premium: boolean }) {
  return (
    <div className="rounded-lg border border-steel-gray/30 bg-charcoal p-4">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs uppercase tracking-wide text-steel-gray">District · Week 8</span>
        <span className="text-xs font-bold uppercase text-green-500">scheduled</span>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-semibold truncate flex-1">{SAMPLE_GAME.homeTeamName} #{idx}</span>
          <span className="font-mono font-bold text-lg ml-4 text-steel-gray">-</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-semibold truncate flex-1">{SAMPLE_GAME.awayTeamName}</span>
          <span className="font-mono font-bold text-lg ml-4 text-steel-gray">-</span>
        </div>
      </div>
      <div className="mt-3 border-t border-steel-gray/20 pt-3">
        <WinProbabilityWithCI
          homeTeamName={SAMPLE_GAME.homeTeamName}
          awayTeamName={SAMPLE_GAME.awayTeamName}
          forecast={SAMPLE_FORECAST}
          variant="compact"
          hideTeamNames
        />
      </div>
      {premium && (
        <details open={expanded} className="mt-3 border-t border-steel-gray/20 pt-3">
          <summary className="cursor-pointer select-none list-none flex items-center justify-between">
            <span className="font-display text-xs uppercase tracking-wide text-silver-print">
              <span className="mr-1">{expanded ? "▾" : "▸"}</span>
              Model Details
            </span>
            <span className="font-body text-[0.65rem] uppercase tracking-wide text-silver-print">premium</span>
          </summary>
          <div className="mt-3"><ModelDetailsBlock data={SAMPLE_PREMIUM} /></div>
        </details>
      )}
    </div>
  );
}

function SectionB() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">B.1 · Premium · 1 of 4 cards expanded</div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <GameCardMock idx={1} premium expanded />
          <GameCardMock idx={2} premium />
          <GameCardMock idx={3} premium />
          <GameCardMock idx={4} premium />
        </div>
      </div>
      <div className="space-y-2">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">B.2 · Non-premium · no toggle on any card</div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <GameCardMock idx={1} premium={false} />
          <GameCardMock idx={2} premium={false} />
          <GameCardMock idx={3} premium={false} />
          <GameCardMock idx={4} premium={false} />
        </div>
      </div>
    </div>
  );
}

// --- Section C · Option 3 — Dashboard new "PREMIUM INSIGHTS" section ---

function TeamCardMock({ name, rating, rank }: { name: string; rating: number; rank: number }) {
  return (
    <div className="rounded-lg border border-steel-gray/30 bg-charcoal p-4">
      <div className="font-display text-sm font-bold text-white">{name}</div>
      <div className="text-xs text-steel-gray mt-1">Rating {rating.toFixed(2)} · Rank #{rank}</div>
    </div>
  );
}

function DashboardMock({ premium }: { premium: boolean }) {
  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-3xl font-bold mb-2 font-display">WELCOME BACK, REESE</h1>
      <p className="text-steel-gray mb-8">Your personalized PrepRank dashboard</p>
      <section className="mb-8">
        <h2 className="text-xl font-bold mb-4 font-display">MY TEAMS</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <TeamCardMock name="Brother Martin" rating={14.21} rank={3} />
          <TeamCardMock name="John Curtis" rating={13.85} rank={5} />
        </div>
      </section>
      <section>
        <h2 className="text-xl font-bold mb-4 font-display">PREMIUM INSIGHTS</h2>
        {premium ? (
          <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-6">
            <div className="font-body text-xs uppercase tracking-wide text-silver-print mb-3">
              Next upcoming game · Brother Martin vs John Curtis · Fri Oct 17
            </div>
            <div className="mb-4 rounded-lg border border-steel-gray/20 bg-charcoal p-4">
              <WinProbabilityWithCI
                homeTeamName={SAMPLE_GAME.homeTeamName}
                awayTeamName={SAMPLE_GAME.awayTeamName}
                forecast={SAMPLE_FORECAST}
                variant="compact"
              />
            </div>
            <ModelDetailsBlock data={SAMPLE_PREMIUM} />
          </div>
        ) : (
          <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-6 text-center">
            <div className="font-display text-base font-bold uppercase tracking-wide mb-2">Premium feature</div>
            <p className="text-sm text-steel-gray mb-4">
              Upgrade to see what&apos;s driving each prediction, comparable historical matchups, and detailed tracking for your favorited teams.
            </p>
            <span className="inline-block rounded bg-crimson px-6 py-2 font-semibold text-white">
              Upgrade to Premium
            </span>
          </div>
        )}
      </section>
    </div>
  );
}

function SectionC() {
  return (
    <div className="space-y-10">
      <div className="space-y-2">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">C.1 · Premium · populated section</div>
        <DashboardMock premium />
      </div>
      <div className="space-y-2">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">C.2 · Non-premium · upgrade teaser</div>
        <DashboardMock premium={false} />
      </div>
    </div>
  );
}

// --- Section D · Option 4 — Reusable drawer in two contexts ---

function SectionD() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">D.1 · Same component mounted on game detail (accordion expanded)</div>
        <GameDetailMock>
          <AccordionToggle open={true}>
            <ModelDetailsBlock data={SAMPLE_PREMIUM} />
          </AccordionToggle>
        </GameDetailMock>
      </div>
      <div className="space-y-2">
        <div className="font-body text-xs uppercase tracking-wide text-silver-print">D.2 · Same component mounted on GameCard list (one card expanded)</div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <GameCardMock idx={1} premium expanded />
          <GameCardMock idx={2} premium />
        </div>
        <div className="font-body text-xs text-silver-print/80 italic">
          Note: the same ModelDetailsBlock helper renders identically in both contexts. Option 4&apos;s engineering cost is the shared component contract — every change to Model Details must satisfy both parent surfaces.
        </div>
      </div>
    </div>
  );
}

// --- Page ---

interface PageProps {
  searchParams?: { only?: string };
}

export default function ModelDetailsOptionsPreviewPage({ searchParams }: PageProps) {
  const only = (searchParams?.only || "").toUpperCase();
  const show = {
    A: !only || only === "A",
    B: !only || only === "B",
    C: !only || only === "C",
    D: !only || only === "D",
  };

  return (
    <main className="min-h-screen bg-charcoal px-6 py-10">
      <div className="mx-auto max-w-7xl space-y-16">
        <header>
          <h1 className="font-display text-3xl font-bold text-white">
            Model Details — 4-option preview (Phase 3.3.4 decision support)
          </h1>
          <p className="mt-2 font-body text-sm text-silver-print max-w-3xl">
            Each section below renders the premium Model Details payload (β
            coefficients, typical-decile chips, predicted-decile reliability,
            methodology kebab-case deep-link) on the actual PrepRank surface
            where that option would land. Same stable sample data across all 4
            sections for fair visual comparison. Decision-support only; nothing
            here is committed to production code paths. Add{" "}
            <code>?only=A</code> | <code>B</code> | <code>C</code> |{" "}
            <code>D</code> to isolate one section.
          </p>
        </header>

        {show.A && (
          <section className="space-y-4">
            <div className="border-l-2 border-crimson pl-3">
              <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-white">Section A · Option 1</h2>
              <p className="font-body text-sm text-silver-print">Inline accordion on game detail page</p>
            </div>
            <SectionA />
          </section>
        )}

        {show.B && (
          <section className="space-y-4">
            <div className="border-l-2 border-crimson pl-3">
              <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-white">Section B · Option 2</h2>
              <p className="font-body text-sm text-silver-print">GameCard per-card expand in list/grid context</p>
            </div>
            <SectionB />
          </section>
        )}

        {show.C && (
          <section className="space-y-4">
            <div className="border-l-2 border-crimson pl-3">
              <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-white">Section C · Option 3</h2>
              <p className="font-body text-sm text-silver-print">Dashboard new &quot;PREMIUM INSIGHTS&quot; section (with content angle: next upcoming game of a favorited team)</p>
            </div>
            <SectionC />
          </section>
        )}

        {show.D && (
          <section className="space-y-4">
            <div className="border-l-2 border-crimson pl-3">
              <h2 className="font-display text-2xl font-bold uppercase tracking-wide text-white">Section D · Option 4</h2>
              <p className="font-body text-sm text-silver-print">Reusable Model Details component mounted on both game detail AND GameCard</p>
            </div>
            <SectionD />
          </section>
        )}

        <footer className="border-t border-steel-gray/20 pt-6 font-body text-xs text-silver-print">
          Internal route. Not in nav. Not indexed. Decision-support preview, NOT
          committed to production code. ModelDetailsBlock helper is local to
          this file; will be extracted to /components/ only after Thomas
          signs off on the surface direction.
        </footer>
      </div>
    </main>
  );
}
