# API Deployment Guide

## Option 1: Railway (Recommended)

### Setup

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click "New Project" → "Deploy from GitHub repo"
3. Select the preprank repository
4. Railway will detect the `Dockerfile.api` at the root

### Configuration

In Railway dashboard → your service → Settings:

- **Root Directory**: leave empty (Dockerfile.api is at repo root)
- **Builder**: Dockerfile
- **Dockerfile Path**: `Dockerfile.api`

### Environment Variables

Add these in Railway → Variables tab:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase pooled connection string (port 6543) |
| `JWT_SECRET_KEY` | Generate: `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `CORS_ORIGINS` | `https://prep-rank.com,https://www.prep-rank.com` |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Your Supabase anon key |
| `PORT` | `8000` (Railway sets this automatically) |

### Custom Domain

1. In Railway → Settings → Networking → Custom Domain
2. Add `api.prep-rank.com`
3. Add CNAME record in your DNS: `api.prep-rank.com` → `<your-app>.up.railway.app`

### Estimated Cost

- Railway Hobby plan: $5/month
- Typical usage at launch: $5-10/month total

---

## Option 2: Fly.io

### Setup

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Deploy
fly launch --config fly.toml --dockerfile Dockerfile.api
```

### Environment Variables

```bash
fly secrets set DATABASE_URL="postgresql://..." JWT_SECRET_KEY="..." CORS_ORIGINS="https://prep-rank.com"
```

### Custom Domain

```bash
fly certs create api.prep-rank.com
```

Then add CNAME: `api.prep-rank.com` → `preprank-api.fly.dev`

---

## Run Migrations on Production

After first deploy, run migrations against the production database:

```bash
# Use the DIRECT Supabase connection (port 5432, not pooler)
DATABASE_URL="postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres" \
  python scripts/deploy_db.py
```

## Verify Deployment

```bash
curl https://api.prep-rank.com/health
# Should return: {"status":"healthy","service":"preprank-api"}

curl https://api.prep-rank.com/api/v1/ratings/rankings?sport=Football&season_year=2025&week_number=11&limit=3
# Should return top 3 ranked teams
```
