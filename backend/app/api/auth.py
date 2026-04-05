from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import (
    authenticate_admin,
    create_access_token,
    is_auth_enabled,
    require_authenticated_user,
)


router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/auth/config")
async def get_auth_config():
    return {"auth_enabled": is_auth_enabled()}


@router.post("/auth/login")
async def login(payload: LoginRequest):
    if not is_auth_enabled():
        return {
            "auth_enabled": False,
            "access_token": None,
            "token_type": "bearer",
            "username": settings.ADMIN_USERNAME,
        }

    user = authenticate_admin(payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

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
