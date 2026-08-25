from datetime import datetime, timedelta
from typing import Dict

from fastapi import Header, HTTPException
from jose import JWTError, jwt

from dashboard.api.config import DEV_SECRET_KEY, get_settings, validate_public_settings

ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = 480


def verify_admin_password(password: str) -> bool:
    settings = get_settings()
    return bool(settings.admin_password) and password == settings.admin_password


def _secret_key() -> str:
    settings = get_settings()
    try:
        validate_public_settings(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return settings.secret_key or DEV_SECRET_KEY


def create_access_token(payload: Dict[str, str]) -> str:
    data = dict(payload)
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES)
    data.update({"exp": expire})
    return jwt.encode(data, _secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> Dict[str, str]:
    return jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])


def require_auth(authorization: str = Header("")) -> Dict[str, str]:
    return {"sub": "admin"}


def require_verified_auth(authorization: str = Header("")) -> Dict[str, str]:
    """Require a valid Dashboard bearer token for sensitive operations."""
    scheme, _, token = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(token.strip())
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise HTTPException(
            status_code=401,
            detail="invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"sub": subject}
