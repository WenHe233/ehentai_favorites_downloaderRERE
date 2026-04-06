from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
import asyncio
import time

from app.core.config import settings
from app.core.security import (
    authenticate_admin,
    create_access_token,
    is_auth_enabled,
    require_authenticated_user,
)


router = APIRouter()

# Simple in-memory rate limiter for login endpoint
_login_attempts: dict[str, list[float]] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 60.0


def _check_login_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    attempts = _login_attempts.get(client_ip, [])
    # Purge old entries
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
    _login_attempts[client_ip] = attempts
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )


def _record_failed_attempt(client_ip: str) -> None:
    now = time.monotonic()
    attempts = _login_attempts.get(client_ip, [])
    attempts.append(now)
    _login_attempts[client_ip] = attempts


def _clear_attempts(client_ip: str) -> None:
    _login_attempts.pop(client_ip, None)


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/auth/config")
async def get_auth_config():
    return {"auth_enabled": is_auth_enabled()}


@router.post("/auth/login")
async def login(payload: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(client_ip)

    if not is_auth_enabled():
        return {
            "auth_enabled": False,
            "access_token": None,
            "token_type": "bearer",
            "username": settings.ADMIN_USERNAME,
        }

    user = authenticate_admin(payload.username, payload.password)
    if not user:
        _record_failed_attempt(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    _clear_attempts(client_ip)
    access_token = create_access_token(user["username"])
    return {
        "auth_enabled": True,
        "access_token": access_token,
        "token_type": "bearer",
        "username": user["username"],
    }


@router.get("/auth/me")
async def get_current_identity(
    current_user: dict = Depends(require_authenticated_user),
):
    return current_user
