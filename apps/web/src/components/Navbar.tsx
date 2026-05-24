"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

const SPORTS = [
  { name: "Football", slug: "football" },
  { name: "Boys Basketball", slug: "boys-basketball" },
  { name: "Girls Basketball", slug: "girls-basketball" },
  { name: "Baseball", slug: "baseball" },
  { name: "Softball", slug: "softball" },
  { name: "Boys Soccer", slug: "boys-soccer" },
  { name: "Girls Soccer", slug: "girls-soccer" },
  { name: "Volleyball", slug: "volleyball" },
];

export default function Navbar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, logout } = useAuth();

  return (
    <nav className="sticky top-0 z-50 border-b border-steel-gray/30 bg-charcoal/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
        <Link href="/" className="flex items-center gap-1">
          <span
            className="text-2xl font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            <span className="text-white">PREP</span>
            <span className="text-crimson">/</span>
            <span className="text-white">RANK</span>
          </span>
        </Link>

        {/* Desktop nav */}
        <div className="hidden md:flex items-center gap-1">
          {SPORTS.map((sport) => {
            const href = `/rankings/${sport.slug}`;
            const isActive = pathname?.startsWith(href);
            return (
              <Link
                key={sport.slug}
                href={href}
                className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-crimson text-white"
                    : "text-steel-gray hover:text-white"
                }`}
              >
                {sport.name}
              </Link>
            );
          })}
          <Link
            href="/scores"
            className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
              pathname?.startsWith("/scores")
                ? "bg-crimson text-white"
                : "text-steel-gray hover:text-white"
            }`}
          >
            Scores
          </Link>
          <Link
            href="/pickem"
            className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
              pathname?.startsWith("/pickem")
                ? "bg-crimson text-white"
                : "text-steel-gray hover:text-white"
            }`}
          >
            Pick&apos;em
          </Link>
          <Link
            href="/scenario"
            className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
              pathname?.startsWith("/scenario")
                ? "bg-crimson text-white"
                : "text-steel-gray hover:text-white"
            }`}
          >
            Scenario Builder
          </Link>
          <div className="ml-4 flex items-center gap-2">
            {user ? (
              <>
                <Link
                  href="/dashboard"
                  className="rounded px-3 py-1.5 text-sm font-medium text-steel-gray hover:text-white transition-colors"
                >
                  Dashboard
                </Link>
                <Link
                  href="/account"
                  className="rounded px-3 py-1.5 text-sm font-medium text-steel-gray hover:text-white transition-colors"
                >
                  {user.first_name || user.email}
                </Link>
                {user.is_admin && (
                  <Link
                    href="/admin/replay"
                    className="rounded px-2 py-1.5 text-xs font-medium text-steel-gray/70 hover:text-crimson transition-colors"
                    title="Admin: Replay QA"
                  >
                    Replay
                  </Link>
                )}
                <button
                  onClick={logout}
                  className="rounded px-3 py-1.5 text-sm font-medium text-steel-gray hover:text-crimson transition-colors"
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link
                  href="/login"
                  className="rounded px-3 py-1.5 text-sm font-medium text-steel-gray hover:text-white transition-colors"
                >
                  Login
                </Link>
                <Link
                  href="/register"
                  className="rounded bg-crimson px-3 py-1.5 text-sm font-semibold text-white hover:bg-crimson/80 transition-colors"
                >
                  Sign Up
                </Link>
              </>
            )}
          </div>
        </div>

        {/* Mobile hamburger */}
        <button
          className="md:hidden text-white p-2"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label="Toggle menu"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {mobileOpen ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            )}
          </svg>
        </button>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="md:hidden border-t border-steel-gray/30 px-4 py-3 space-y-1">
          {SPORTS.map((sport) => (
            <Link
              key={sport.slug}
              href={`/rankings/${sport.slug}`}
              className="block rounded px-3 py-2 text-sm text-steel-gray hover:text-white hover:bg-crimson/10"
              onClick={() => setMobileOpen(false)}
            >
              {sport.name}
            </Link>
          ))}
          <Link
            href="/scores"
            className="block rounded px-3 py-2 text-sm text-steel-gray hover:text-white hover:bg-crimson/10"
            onClick={() => setMobileOpen(false)}
          >
            Scores
          </Link>
          <Link
            href="/pickem"
            className="block rounded px-3 py-2 text-sm text-steel-gray hover:text-white hover:bg-crimson/10"
            onClick={() => setMobileOpen(false)}
          >
            Pick&apos;em
          </Link>
          <Link
            href="/scenario"
            className="block rounded px-3 py-2 text-sm text-steel-gray hover:text-white hover:bg-crimson/10"
            onClick={() => setMobileOpen(false)}
          >
            Scenario Builder
          </Link>
          <div className="border-t border-steel-gray/30 mt-2 pt-2">
            {user ? (
              <>
                <Link
                  href="/dashboard"
                  className="block rounded px-3 py-2 text-sm text-steel-gray hover:text-white hover:bg-crimson/10"
                  onClick={() => setMobileOpen(false)}
                >
                  Dashboard
                </Link>
                <Link
                  href="/account"
                  className="block rounded px-3 py-2 text-sm text-steel-gray hover:text-white hover:bg-crimson/10"
                  onClick={() => setMobileOpen(false)}
                >
                  {user.first_name || user.email}
                </Link>
                {user.is_admin && (
                  <Link
                    href="/admin/replay"
                    className="block rounded px-3 py-2 text-sm text-steel-gray hover:text-crimson hover:bg-crimson/10"
                    onClick={() => setMobileOpen(false)}
                  >
                    Admin · Replay QA
                  </Link>
                )}
                <button
                  onClick={() => { logout(); setMobileOpen(false); }}
                  className="block w-full text-left rounded px-3 py-2 text-sm text-steel-gray hover:text-crimson hover:bg-crimson/10"
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link
                  href="/login"
                  className="block rounded px-3 py-2 text-sm text-steel-gray hover:text-white hover:bg-crimson/10"
                  onClick={() => setMobileOpen(false)}
                >
                  Login
                </Link>
                <Link
                  href="/register"
                  className="block rounded px-3 py-2 text-sm font-semibold text-crimson hover:bg-crimson/10"
                  onClick={() => setMobileOpen(false)}
                >
                  Sign Up
                </Link>
              </>
            )}
          </div>
        </div>
      )}
    </nav>
  );
}
