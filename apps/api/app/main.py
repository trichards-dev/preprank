from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import schools, teams, games, ratings, simulations, auth, subscriptions, favorites, pickem, share, hype, scenarios, admin_replay

app = FastAPI(
    title="PrepRank API",
    description="LHSAA Power Rankings & Predictions",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(schools.router, prefix="/api/v1/schools", tags=["schools"])
app.include_router(teams.router, prefix="/api/v1/teams", tags=["teams"])
app.include_router(games.router, prefix="/api/v1/games", tags=["games"])
app.include_router(ratings.router, prefix="/api/v1/ratings", tags=["ratings"])
app.include_router(simulations.router, prefix="/api/v1/simulations", tags=["simulations"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(subscriptions.router, prefix="/api/v1/subscriptions", tags=["subscriptions"])
app.include_router(favorites.router, prefix="/api/v1/favorites", tags=["favorites"])
app.include_router(pickem.router, prefix="/api/v1/pickem", tags=["pickem"])
app.include_router(share.router, prefix="/api/v1/share", tags=["share"])
app.include_router(hype.router, prefix="/api/v1/hype", tags=["hype"])
app.include_router(scenarios.router, prefix="/api/v1/scenarios", tags=["scenarios"])
app.include_router(admin_replay.router, prefix="/api/v1/admin/replay", tags=["admin"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "preprank-api"}
