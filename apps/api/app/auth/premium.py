from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from app.models import User
from app.auth.dependencies import get_current_user, get_optional_user


PREMIUM_TIERS = {"premium_monthly", "season_pass", "annual"}


def _is_premium(user: User) -> bool:
    if user.subscription_tier not in PREMIUM_TIERS:
        return False
    if user.subscription_expires and user.subscription_expires.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return False
    return True


def require_premium(current_user: User = Depends(get_current_user)) -> User:
    if not _is_premium(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upgrade to PrepRank Premium to access projections and predictions",
        )
    return current_user


def get_premium_or_preview(
    current_user: User | None = Depends(get_optional_user),
) -> dict:
    """Returns {"user": User|None, "is_premium": bool, "preview_allowed": bool}."""
    if current_user is None:
        return {"user": None, "is_premium": False, "preview_allowed": True}
    if _is_premium(current_user):
        return {"user": current_user, "is_premium": True, "preview_allowed": True}
    return {"user": current_user, "is_premium": False, "preview_allowed": True}


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Gate endpoints to admin users. Returns 404 (not 403) to hide existence."""
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return current_user
