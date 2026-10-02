from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.config import settings


ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def is_auth_enabled() -> bool:
    settings.reload()
    return bool(settings.ENABLE_AUTH)


def authenticate_admin(username: str, password: str) -> Optional[Dict[str, Any]]:
    settings.reload()
    if not settings.ENABLE_AUTH:
        return {"username": settings.ADMIN_USERNAME, "auth_enabled": False}

    if not (
        secrets.compare_digest(username.encode(), settings.ADMIN_USERNAME.encode())
        and secrets.compare_digest(password.encode(), settings.ADMIN_PASSWORD.encode())
    ):
        return None

    return {"username": settings.ADMIN_USERNAME, "auth_enabled": True}


def create_access_token(subject: str) -> str:
    settings.reload()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": subject,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


async def require_authenticated_user(
    token: str | None = Depends(oauth2_scheme),
) -> Dict[str, Any]:
    settings.reload()
    if not settings.ENABLE_AUTH:
        return {"username": settings.ADMIN_USERNAME, "auth_enabled": False}

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
    except JWTError as exc:
        raise credentials_exception from exc

    if not isinstance(username, str) or not secrets.compare_digest(username.encode(), settings.ADMIN_USERNAME.encode()):
        raise credentials_exception

    return {"username": username, "auth_enabled": True}
