from fastapi import Depends, HTTPException, Request

from .config import get_settings
from .database import Store
from .security import require_roles, session_claims

settings = get_settings()
store = Store(settings)


def get_store(_: Request) -> Store:
    return store


async def require_active_user(claims=Depends(session_claims), current_store=Depends(get_store)):
    user = await current_store.find_one("users", {"_id": claims["sub"]})
    if not user or user.get("status") != "ACTIVE":
        raise HTTPException(status_code=403, detail="Account is inactive")
    if user.get("role") != claims.get("role"):
        raise HTTPException(status_code=403, detail="Account role has changed. Sign in again")
    return claims


def require_active_roles(*roles: str):
    async def dependency(claims=Depends(require_active_user)):
        if claims.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permission")
        return claims
    return dependency


async def require_active_driver(claims=Depends(require_active_roles("DRIVER"))):
    return claims


async def require_verified_driver(claims=Depends(require_active_driver), current_store=Depends(get_store)):
    profile = await current_store.find_one("drivers", {"user_id": claims["sub"]})
    if not profile or profile.get("verification_status") != "VERIFIED":
        raise HTTPException(status_code=403, detail="Driver account is waiting for admin approval")
    return claims