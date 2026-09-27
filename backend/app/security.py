import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from secrets import token_bytes

import jwt
from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings


def generate_salt() -> str:
    return base64.urlsafe_b64encode(token_bytes(16)).decode("ascii")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    password_salt = salt or generate_salt()
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=base64.urlsafe_b64decode(password_salt.encode("ascii")),
        n=2**14,
        r=8,
        p=1,
        dklen=64,
    )
    return base64.urlsafe_b64encode(derived).decode("ascii"), password_salt


def verify_password(password: str, encoded: str, salt: str) -> bool:
    if not salt:
        return False
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, encoded)


def create_session_token(user_id: str, role: str, name: str, email: str, phone: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user_id,
            "role": role,
            "name": name,
            "email": email,
            "phone": phone,
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
        },
        settings.secret_key,
        algorithm="HS256",
    )


async def session_claims(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        return jwt.decode(authorization.removeprefix("Bearer ").strip(), settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from exc


async def optional_session_claims(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, str] | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return jwt.decode(authorization.removeprefix("Bearer ").strip(), settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def require_roles(*roles: str):
    async def dependency(claims: dict[str, str] = Depends(session_claims)) -> dict[str, str]:
        if claims.get("role") not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
        return claims

    return dependency


async def verify_access_token(_: dict[str, str] = Depends(session_claims)) -> None:
    """Require a valid bearer JWT for a state-changing operation."""
