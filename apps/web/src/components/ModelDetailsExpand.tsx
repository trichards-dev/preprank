import Link from "next/link";
import type { FactorImpact, PremiumDetail } from "@/lib/api";

// Phase 3.3.4b (2026-05-30): raw beta coefficients + numeric per-decile
// reliability are NO LONGER displayed at any tier. Premium drawer surfaces
// qualitative factor impact + descriptive reliability + typical-decile +
// methodology deep-link only. See claude-memory decisions.md 2026-05-30
// entry "Phase 3.3.4b — coefficient exposure removed".

interface ModelDetailsExpandProps {
  premiumDetail: PremiumDetail;
  sport: string;
  panelId: string;
  labelledById: string;
}

const IMPACT_LABEL: Record<FactorImpact, string> = {
  high: "High impact",
  moderate: "Moderate impact",
  low: "Low impact",
};

const IMPACT_CLASSES: Record<FactorImpact, string> = {
  high: "bg-crimson/20 text-white",
  moderate: "bg-steel-gray/20 text-silver-print",
  low: "bg-steel-gray/10 text-silver-print",
};

export default function ModelDetailsExpand({
  premiumDetail,
  sport,
  panelId,
  labelledById,
}: ModelDetailsExpandProps) {
  const displayDecile = premiumDetail.predicted_decile + 1;
  const factors = premiumDetail.factor_contributions;

  return (
    <div
      id={panelId}
      role="region"
      aria-labelledby={labelledById}
      className="mt-3 space-y-3 font-body"
    >
      <div>
        <div className="font-display text-[0.65rem] uppercase tracking-wide text-silver-print mb-1">
          What&apos;s driving this prediction · {sport}
        </div>
        {factors.length === 0 ? (
          <div className="text-xs text-silver-print">
            Factor data unavailable for this prediction.
          </div>
        ) : (
          <ul className="space-y-1">
            {factors.map((fc) => (
              <li
                key={fc.label}
                className="flex items-center justify-between gap-2 border-b border-steel-gray/15 py-1"
              >
                <span className="text-xs text-white truncate pr-2">
                  {fc.label}
                </span>
                <span
                  className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[0.6rem] uppercase tracking-wide whitespace-nowrap ${IMPACT_CLASSES[fc.impact]}`}
                >
                  {IMPACT_LABEL[fc.impact]}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded border border-steel-gray/20 p-2">
          <div className="font-display uppercase tracking-wide text-silver-print text-[0.65rem]">
            Home typical decile
          </div>
          <div className="mt-1 font-display text-lg text-white">
            {premiumDetail.home_typical_decile !== null
              ? `D${premiumDetail.home_typical_decile}`
              : "—"}
          </div>
        </div>
        <div className="rounded border border-steel-gray/20 p-2">
          <div className="font-display uppercase tracking-wide text-silver-print text-[0.65rem]">
            Away typical decile
          </div>
          <div className="mt-1 font-display text-lg text-white">
            {premiumDetail.away_typical_decile !== null
              ? `D${premiumDetail.away_typical_decile}`
              : "—"}
          </div>
        </div>
      </div>

      <div className="rounded border border-steel-gray/20 p-2 text-xs">
        <div className="font-display uppercase tracking-wide text-silver-print text-[0.65rem]">
          Predicted decile · D{displayDecile}
        </div>
        {premiumDetail.predicted_decile_reliability ? (
          <div className="mt-1 text-silver-print">
            {premiumDetail.predicted_decile_reliability.description}
          </div>
        ) : (
          <div className="mt-1 text-silver-print">
            Reliability data unavailable for this decile.
          </div>
        )}
      </div>

      <Link
        href={premiumDetail.methodology_deep_link}
        className="inline-block text-xs text-crimson hover:underline font-body"
      >
        Read methodology for {sport} D{displayDecile} →
      </Link>
    </div>
  );
}
