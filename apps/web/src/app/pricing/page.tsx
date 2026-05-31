"use client";

import { useAuth } from "@/lib/auth";
import Link from "next/link";

const TIERS = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    features: ["Power Rankings", "Scores & Schedules", "Team Pages", "Basic Stats"],
    locked: ["Projections", "What's At Stake", "Scenario Builder", "My Teams Dashboard"],
    cta: null,
    tier: "free",
  },
  {
    name: "Premium Monthly",
    price: "$4.99",
    period: "/month",
    features: ["Everything in Free", "Monte Carlo Projections", "What's At Stake Analysis", "Per-Game Model Details (factor impact)", "Playoff Probability", "Championship Odds", "My Teams Dashboard"],
    locked: [],
    cta: "Start Monthly",
    tier: "premium_monthly",
    popular: true,
  },
  {
    name: "Season Pass",
    price: "$14.99",
    period: "/season",
    features: ["Everything in Premium", "One Sport Season", "Save vs Monthly"],
    locked: [],
    cta: "Get Season Pass",
    tier: "season_pass",
  },
  {
    name: "Annual",
    price: "$29.99",
    period: "/year",
    features: ["Everything in Premium", "All Sports, All Year", "Best Value"],
    locked: [],
    cta: "Go Annual",
    tier: "annual",
  },
];

export default function PricingPage() {
  const { user } = useAuth();

  return (
    <main className="mx-auto max-w-6xl px-4 py-12">
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold mb-4" style={{ fontFamily: "var(--font-display)" }}>
          <span className="text-white">PREP</span>
          <span className="text-crimson">/</span>
          <span className="text-white">RANK</span>
          <span className="text-crimson"> PREMIUM</span>
        </h1>
        <p className="text-steel-gray text-lg">Unlock predictions, projections, and playoff probabilities</p>
      </div>

      <div className="grid md:grid-cols-4 gap-6">
        {TIERS.map((tier) => (
          <div key={tier.tier}
            className={`rounded-lg border p-6 flex flex-col ${tier.popular ? "border-crimson bg-crimson/5" : "border-steel-gray/30"}`}>
            {tier.popular && (
              <span className="text-xs font-bold text-crimson uppercase tracking-wide mb-2">Most Popular</span>
            )}
            <h3 className="text-xl font-bold mb-1" style={{ fontFamily: "var(--font-display)" }}>{tier.name}</h3>
            <div className="mb-4">
              <span className="text-3xl font-bold">{tier.price}</span>
              <span className="text-steel-gray text-sm">{tier.period}</span>
            </div>
            <ul className="space-y-2 mb-6 flex-1">
              {tier.features.map((f) => (
                <li key={f} className="text-sm flex items-start gap-2">
                  <span className="text-green-500 mt-0.5">&#10003;</span>
                  <span>{f}</span>
                </li>
              ))}
              {tier.locked.map((f) => (
                <li key={f} className="text-sm flex items-start gap-2 text-steel-gray">
                  <span className="mt-0.5">&#10007;</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            {tier.cta && (
              <Link
                href={user ? "/account" : "/register"}
                className={`block text-center rounded py-2.5 font-semibold transition-colors ${
                  tier.popular
                    ? "bg-crimson text-white hover:bg-crimson/80"
                    : "border border-steel-gray text-white hover:border-crimson"
                }`}
              >
                {tier.cta}
              </Link>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}
