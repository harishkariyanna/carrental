from fastapi import Depends, HTTPException, Request

from .config import get_settings
from .database import Store
from .security import require_roles

settings = get_settings()
store = Store(settings)


def get_store(_: Request) -> Store:
    return store


async def require_verified_driver(claims=Depends(require_roles("DRIVER")), current_store=Depends(get_store)):
    profile = await current_store.find_one("drivers", {"user_id": claims["sub"]})
    if not profile or profile.get("verification_status") != "VERIFIED":
        raise HTTPException(status_code=403, detail="Driver account is waiting for admin approval")
    return claims