# Web Frontend Deployment Guide (Vercel)

## 1. Connect Repository

1. Go to [vercel.com](https://vercel.com) and sign in with GitHub
2. Click "Add New..." → "Project"
3. Import the `preprank` repository
4. Configure:
   - **Framework Preset**: Next.js
   - **Root Directory**: `apps/web`
   - **Build Command**: `npm run build` (default)
   - **Output Directory**: `.next` (default)

## 2. Environment Variables

Add in Vercel → Settings → Environment Variables:

| Variable | Value | Environment |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.prep-rank.com` | Production |
| `NEXT_PUBLIC_API_URL` | `https://api-staging.prep-rank.com` | Preview |

## 3. Custom Domain

1. In Vercel → Settings → Domains
2. Add `prep-rank.com`
3. Add `www.prep-rank.com` (redirects to prep-rank.com)
4. DNS Configuration:
   - **A Record**: `prep-rank.com` → `76.76.21.21`
   - **CNAME**: `www.prep-rank.com` → `cname.vercel-dns.com`

## 4. Verify

After deployment:
```bash
curl -s https://prep-rank.com | grep "PREP/RANK"
# Should contain the PREP/RANK title

# Test OG tags
curl -s https://prep-rank.com/teams/1 | grep "og:title"
```

## Monorepo Configuration

Vercel needs to know this is a monorepo:
- Root Directory is set to `apps/web`
- Install command uses workspace root: `npm install` (from monorepo root)
- Vercel auto-detects npm workspaces

### Ignored Builds

The `vercel.json` `ignoreCommand` ensures Vercel only rebuilds when `apps/web/` or `packages/shared/` change. API-only changes don't trigger a web rebuild.

## Estimated Cost

- Vercel Hobby (free): 100GB bandwidth, sufficient for launch
- Vercel Pro ($20/month): if you need more bandwidth or team features
