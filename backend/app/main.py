from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.security import require_authenticated_user
from app.db.database import SessionLocal, init_models
from app.db.models import AppConfig
from loguru import logger
from sqlalchemy.future import select
import sys
import asyncio

# Configure Logger
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
)
logger.add(settings.DATA_DIR / "app.log", rotation="10 MB", level="DEBUG")

app = FastAPI(
    title=settings.APP_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="Backend for ehentai_favorites_downloaderRERE",
    version="1.0.0",
)

cors_allow_origins = settings.CORS_ALLOW_ORIGINS or []
allow_all_origins = "*" in cors_allow_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all_origins else cors_allow_origins,
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.auth import router as auth_router
from app.api.endpoints import router as api_router
from app.services.downloader import downloader
from app.services.scheduler import start_scheduler
from app.services.notification_service import NOTIFICATION_BUFFER_KEY, notification_service
from app.services.startup_recovery import startup_recovery_service

from app.services.bot import start_bot
from app.services.config_service import config_service

app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(
    api_router,
    prefix=settings.API_V1_STR,
    dependencies=[Depends(require_authenticated_user)],
)

@app.on_event("startup")
async def startup_event():
    logger.info("Initializing database models...")
    await init_models()

    if settings.ENABLE_AUTH:
        logger.info("API authentication is enabled.")
        if settings.ADMIN_USERNAME == "admin" and settings.ADMIN_PASSWORD == "admin":
            logger.warning("Authentication is enabled but admin credentials are still the default admin/admin.")
    else:
        logger.warning("API authentication is disabled. Only use this mode on trusted networks.")

    if allow_all_origins:
        logger.warning("CORS is configured with wildcard origins.")
    elif not cors_allow_origins:
        logger.info("CORS allow list is empty. Only same-origin requests will work in browsers.")

    temp_cookies_path = settings.DATA_DIR / "temp_cookies.txt"
    if temp_cookies_path.exists():
        logger.warning(f"Legacy temp cookies file detected: {temp_cookies_path}")

    legacy_download_archive = settings.BASE_DIR / "downloads.zip"
    if legacy_download_archive.exists():
        logger.warning(f"Legacy download archive detected: {legacy_download_archive}")

    async with SessionLocal() as session:
        result = await session.execute(
            select(AppConfig.key).where(
                AppConfig.key.not_in({"sync_state", NOTIFICATION_BUFFER_KEY})
            )
        )
        legacy_app_config_keys = result.scalars().all()
    if legacy_app_config_keys:
        logger.warning(
            "Legacy config keys still exist in app_config: "
            + ", ".join(sorted(legacy_app_config_keys))
        )

    recovery_summary = await startup_recovery_service.recover_interrupted_downloads()
    if recovery_summary.recovered_total:
        logger.warning(
            "Startup recovery re-queued interrupted tasks: "
            f"{recovery_summary.recovered_total} total, "
            f"{recovery_summary.native_resume_total} with native resume data, "
            f"{recovery_summary.archive_requeue_total} archive restarts"
        )

    restored_notification_count = await notification_service.initialize()
    if restored_notification_count:
        logger.warning(
            f"Restored {restored_notification_count} buffered Telegram notification(s) after startup."
        )
    
    # Re-enable downloader with proper isolation
    logger.info("Starting Downloader Service...")
    try:
        asyncio.create_task(downloader.start())
    except Exception as e:
        logger.error(f"Downloader start error: {e}")

    runtime_settings = await config_service.get_all_settings()

    if runtime_settings.get("auto_sync"):
        logger.info("Starting Scheduler...")
        start_scheduler()

    if runtime_settings.get("telegram_bot_token"):
        logger.info("Starting Telegram Bot...")
        asyncio.create_task(start_bot())
    
    logger.info("Application startup complete.")

