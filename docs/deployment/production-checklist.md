# PrepRank Production Launch Checklist

## Infrastructure

- [ ] Supabase project created (`preprank`, us-east-1)
- [ ] Database password stored securely (1Password/Bitwarden)
- [ ] All Alembic migrations run against Supabase (`scripts/deploy_db.py`)
- [ ] 2025 football data seeded (298 schools, 298 teams, 298 ratings)
- [ ] API deployed to Railway (or Fly.io)
- [ ] Web deployed to Vercel

## Domains & SSL

- [ ] `prep-rank.com` DNS pointing to Vercel
- [ ] `www.prep-rank.com` redirecting to `prep-rank.com`
- [ ] `api.prep-rank.com` DNS pointing to Railway/Fly
- [ ] SSL certificates active on all domains (auto-provisioned)

## Environment Variables

### API (Railway)
- [ ] `DATABASE_URL` — Supabase pooled connection (port 6543)
- [ ] `JWT_SECRET_KEY` — strong random value (NOT the dev default)
- [ ] `CORS_ORIGINS` — `https://prep-rank.com,https://www.prep-rank.com`
- [ ] `SUPABASE_URL` — project URL
- [ ] `SUPABASE_KEY` — anon key

### Web (Vercel)
- [ ] `NEXT_PUBLIC_API_URL` — `https://api.prep-rank.com`

## Security

- [ ] JWT_SECRET_KEY is NOT `preprank-dev-secret-change-in-production`
- [ ] CORS only allows production domains (not localhost)
- [ ] Supabase Row Level Security enabled on user-facing tables
- [ ] Database password is strong (32+ chars)
- [ ] No `.env` files committed to git
- [ ] API rate limiting considered (FastAPI SlowAPI or Supabase)

## Payments

- [ ] Stripe account created (can be test mode at launch)
- [ ] Stripe API keys added to Railway env vars when ready
- [ ] Webhook endpoint configured in Stripe dashboard

## Testing (on production)

- [ ] `curl https://api.prep-rank.com/health` returns `{"status":"healthy"}`
- [ ] Rankings page loads at `https://prep-rank.com/rankings/football`
- [ ] All 298 teams visible with correct ratings
- [ ] Register a new account → login → view dashboard
- [ ] Follow a team → appears on dashboard
- [ ] Premium upgrade flow works (mock/test mode)
- [ ] Pick'em contest creation and scoring
- [ ] Scenario Builder loads for premium user
- [ ] Share image generation: `https://api.prep-rank.com/api/v1/share/team/1/image`
- [ ] OG meta tags render correctly (test with https://www.opengraph.xyz/)
- [ ] Mobile responsive: test on phone browser

## Monitoring

- [ ] Sentry error tracking configured (free tier: sentry.io)
  - Add `SENTRY_DSN` to both API and web environment variables
- [ ] Uptime monitoring (UptimeRobot or similar, free)
  - Monitor: `https://api.prep-rank.com/health`
  - Monitor: `https://prep-rank.com`
- [ ] Google Analytics or Plausible for traffic tracking
  - Add tracking script to `apps/web/src/app/layout.tsx`

## CI/CD

- [ ] GitHub Actions secrets configured:
  - `RAILWAY_TOKEN` (from Railway dashboard)
  - `VERCEL_TOKEN` (from Vercel dashboard)
  - `VERCEL_ORG_ID` (from Vercel CLI: `vercel link`)
  - `VERCEL_PROJECT_ID` (from Vercel CLI: `vercel link`)
- [ ] CI pipeline runs on PR (tests + build)
- [ ] Deploy pipeline triggers on merge to main

## Pre-Launch Communication

- [ ] App Store listing copy ready (from GTM doc Section 9)
- [ ] Landing page live at prep-rank.com
- [ ] Social media accounts created (@PrepRankLA)
- [ ] Beta tester list compiled (200 target)
- [ ] Press kit assembled (from GTM doc Section 12)
