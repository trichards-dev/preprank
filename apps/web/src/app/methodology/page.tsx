import type { Metadata } from "next";
import Link from "next/link";
import reliabilityTable from "@/data/reliability_table.json";

export const metadata: Metadata = {
  title: "How PrepRank Rankings Work — Methodology",
  description:
    "How PrepRank predicts LHSAA high school games and ranks teams across eight sports, with per-sport reliability outcomes and transparency about prediction confidence.",
  openGraph: {
    title: "How PrepRank Rankings Work — Methodology",
    description:
      "How PrepRank predicts games and ranks teams across LHSAA high school sports.",
    type: "article",
  },
};

// --- Sport ordering + slug map (matches engine kebab-case convention) ---

const SPORTS: Array<{ name: string; slug: string }> = [
  { name: "Football", slug: "football" },
  { name: "Boys Basketball", slug: "boys-basketball" },
  { name: "Girls Basketball", slug: "girls-basketball" },
  { name: "Baseball", slug: "baseball" },
  { name: "Softball", slug: "softball" },
  { name: "Boys Soccer", slug: "boys-soccer" },
  { name: "Girls Soccer", slug: "girls-soccer" },
  { name: "Volleyball", slug: "volleyball" },
];

// --- Per-sport status (computed from reliability data; abstract booleans only) ---

interface SportData {
  isotonic_slope: number;
  isotonic_slope_in_band: boolean;
  deciles: Array<{ n_games: number }>;
  tail_miscalibration_after_isotonic: boolean;
}

type SportStatus = "passed" | "minor_variance" | "limited_data";

interface StatusInfo {
  label: string;
  context: string;
  badgeClasses: string;
}

const STATUS_INFO: Record<SportStatus, StatusInfo> = {
  passed: {
    label: "PASSED",
    context: "Predictions match observed outcomes within our confidence band.",
    badgeClasses: "bg-steel-gray/20 text-white",
  },
  minor_variance: {
    label: "MINOR VARIANCE",
    context: "Predictions show some variance from observed outcomes; tier labels reflect this added uncertainty.",
    badgeClasses: "bg-steel-gray/20 text-silver-print",
  },
  limited_data: {
    label: "LIMITED DATA",
    context: "Limited historical data for this sport; predictions carry wider confidence ranges.",
    badgeClasses: "bg-steel-gray/20 text-silver-print",
  },
};

function sportStatus(s: SportData): SportStatus {
  const totalN = s.deciles.reduce((sum, d) => sum + d.n_games, 0);
  if (totalN < 200) return "limited_data";
  if (s.isotonic_slope_in_band && !s.tail_miscalibration_after_isotonic) return "passed";
  return "minor_variance";
}

// --- Per-sport section (preserves 80 anchor IDs at sport granularity) ---

function SportSection({ name, slug, sport, lastUpdated }: {
  name: string;
  slug: string;
  sport: SportData;
  lastUpdated: string | undefined;
}) {
  const status = sportStatus(sport);
  const info = STATUS_INFO[status];

  return (
    <section id={slug} className="scroll-mt-20 rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-5 space-y-2">
      {/* Preserve all 10 per-decile anchor IDs for backward-compat with 3.3.4 Model Details deep-links */}
      {Array.from({ length: 10 }, (_, i) => (
        <span
          key={i}
          id={`${slug}-d${i + 1}`}
          aria-hidden="true"
          className="block h-0 w-0 scroll-mt-20"
        />
      ))}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-xl font-bold uppercase tracking-wide">
          {name}
        </h3>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 font-body text-xs uppercase tracking-wide ${info.badgeClasses}`}
        >
          {info.label}
        </span>
      </div>
      <p className="text-sm text-silver-print">{info.context}</p>
      {lastUpdated && (
        <p className="text-xs text-silver-print">
          Last evaluated:{" "}
          <time dateTime={lastUpdated}>
            {new Date(lastUpdated).toLocaleDateString("en-US", {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
          </time>
        </p>
      )}
    </section>
  );
}

// --- Page ---

export default function MethodologyPage() {
  const sports = reliabilityTable.sports as Record<string, SportData>;
  const generatedUtc = (reliabilityTable as { generated_utc?: string }).generated_utc;

  return (
    <main className="mx-auto max-w-3xl px-4 py-10 space-y-12 font-body text-white">
      {/* 1. Hero */}
      <header className="space-y-3">
        <h1 className="font-display text-4xl font-bold uppercase tracking-tight">
          How We Make the Call
        </h1>
        <p className="text-silver-print max-w-2xl">
          Most HS sports apps show you a number. PrepRank shows you the
          number, the math behind it, and how often we&apos;re right. Eight
          sports. Eighty prediction buckets. Every assumption on the page
          below.
        </p>
      </header>

      {/* 2. How we make predictions */}
      <section className="space-y-3">
        <h2 className="font-display text-2xl font-bold uppercase tracking-wide">
          How we make predictions
        </h2>
        <p>
          PrepRank predicts every game and ranks every team using historical
          results, opponent strength, recent performance, and other factors.
          Our model is updated continuously as new games are played.
        </p>
      </section>

      {/* 3. Tier definitions (no CI half-width annotations) */}
      <section className="space-y-4">
        <h2 className="font-display text-2xl font-bold uppercase tracking-wide">
          Tier definitions
        </h2>
        <p className="text-silver-print">
          Every PrepRank prediction comes with a confidence range. We label
          each prediction based on how wide that range is — the wider the
          range, the less certain we are.
        </p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-4">
            <div className="font-display text-lg font-bold uppercase tracking-wide">
              Confident pick
            </div>
            <p className="text-sm mt-2">
              Strong evidence for one side. Most district matchups with two
              well-tracked teams land here.
            </p>
          </div>
          <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-4">
            <div className="font-display text-lg font-bold uppercase tracking-wide">Lean</div>
            <p className="text-sm mt-2">
              We have a clear favorite, but the underdog has a real shot.
            </p>
          </div>
          <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-4">
            <div className="font-display text-lg font-bold uppercase tracking-wide">Toss-up</div>
            <p className="text-sm mt-2">
              Closer to a coin flip than a confident call.
            </p>
          </div>
          <div className="rounded-lg border border-steel-gray/30 bg-charcoal-elevated p-4">
            <div className="font-display text-lg font-bold uppercase tracking-wide">Long shot</div>
            <p className="text-sm mt-2">
              Extreme prediction with limited supporting data. Treat skeptically.
            </p>
          </div>
        </div>
      </section>

      {/* 4. When we hold back */}
      <section className="space-y-3">
        <h2 className="font-display text-2xl font-bold uppercase tracking-wide">
          When we hold back
        </h2>
        <p>
          When we don&apos;t have enough data to be confident, we say so.
          Rare matchups, brand-new teams, and prediction ranges where
          we&apos;ve seen few historical examples all reduce our confidence.
          We&apos;d rather be honest about what we don&apos;t yet know than
          overstate certainty.
        </p>
      </section>

      {/* 5. Per-sport accountability */}
      <section className="space-y-4">
        <h2 className="font-display text-2xl font-bold uppercase tracking-wide">
          Per-sport accountability
        </h2>
        <p className="text-silver-print">
          We check each sport&apos;s predictions against actual game
          outcomes. Status reflects whether our predictions matched
          observations, plus how much historical data the sport has.
        </p>
        <div className="space-y-3">
          {SPORTS.map(({ name, slug }) => {
            const sport = sports[name];
            if (!sport) return null;
            return (
              <SportSection
                key={slug}
                name={name}
                slug={slug}
                sport={sport}
                lastUpdated={generatedUtc}
              />
            );
          })}
        </div>
      </section>

      {/* 6. Baseball source-data note */}
      <section className="space-y-3">
        <h2 className="font-display text-2xl font-bold uppercase tracking-wide">
          Source-data note (Baseball)
        </h2>
        <p>
          Baseball games on lhsaaonline.org are sometimes recorded with only
          the winning team&apos;s runs. PrepRank&apos;s Baseball forecasts
          use win/loss outcomes (which aren&apos;t affected), and Baseball
          game cards carry an additional source-data note alongside the
          prediction.
        </p>
      </section>

      {/* 7. Premium upsell */}
      <section className="rounded-lg border border-crimson/40 bg-charcoal-elevated p-6 space-y-3">
        <h2 className="font-display text-2xl font-bold uppercase tracking-wide">
          Want more depth?
        </h2>
        <p>
          PrepRank Premium shows the factors driving each prediction,
          comparable historical matchups, and detailed tracking for your
          favorited teams.
        </p>
        <Link
          href="/pricing"
          className="inline-block rounded bg-crimson px-6 py-2 font-semibold text-white hover:bg-crimson/80 transition-colors"
        >
          See Premium
        </Link>
      </section>
    </main>
  );
}
