from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import delete
from sqlalchemy.future import select

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import AppConfig
from app.services.notification_service import NOTIFICATION_BUFFER_KEY


RESERVED_APP_CONFIG_KEYS = {"sync_state", NOTIFICATION_BUFFER_KEY}


async def get_legacy_state() -> Dict[str, Any]:
    temp_cookies_path = settings.DATA_DIR / "temp_cookies.txt"
    downloads_zip_path = settings.BASE_DIR / "downloads.zip"

    async with SessionLocal() as session:
        result = await session.execute(select(AppConfig.key).order_by(AppConfig.key))
        all_keys = list(result.scalars().all())

    legacy_keys = [key for key in all_keys if key not in RESERVED_APP_CONFIG_KEYS]

    return {
        "legacy_app_config_keys": legacy_keys,
        "legacy_app_config_count": len(legacy_keys),
        "temp_cookies_exists": temp_cookies_path.exists(),
        "temp_cookies_path": str(temp_cookies_path),
        "downloads_zip_exists": downloads_zip_path.exists(),
        "downloads_zip_path": str(downloads_zip_path),
    }


def _safe_unlink(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    path.unlink()
    return True


async def cleanup_legacy_state(
    *,
    cleanup_app_config: bool = False,
    cleanup_temp_cookies: bool = False,
    cleanup_downloads_zip: bool = False,
) -> Dict[str, Any]:
    removed_app_config_keys: List[str] = []
    removed_files: List[str] = []

    if cleanup_app_config:
        async with SessionLocal() as session:
            result = await session.execute(
                select(AppConfig.key).where(AppConfig.key.not_in(RESERVED_APP_CONFIG_KEYS))
            )
            removed_app_config_keys = list(result.scalars().all())
            if removed_app_config_keys:
                await session.execute(
                    delete(AppConfig).where(AppConfig.key.not_in(RESERVED_APP_CONFIG_KEYS))
                )
                await session.commit()

    if cleanup_temp_cookies:
        temp_cookies_path = settings.DATA_DIR / "temp_cookies.txt"
        if _safe_unlink(temp_cookies_path):
            removed_files.append(str(temp_cookies_path))

    if cleanup_downloads_zip:
        downloads_zip_path = settings.BASE_DIR / "downloads.zip"
        if _safe_unlink(downloads_zip_path):
            removed_files.append(str(downloads_zip_path))

    state = await get_legacy_state()
    return {
        "removed_app_config_keys": removed_app_config_keys,
        "removed_files": removed_files,
        "state": state,
    }
