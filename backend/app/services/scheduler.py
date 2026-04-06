from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.config import settings
from app.services.updater import updater
from app.services.downloader import downloader
from loguru import logger

scheduler = AsyncIOScheduler()

def start_scheduler():
    if scheduler.running:
        logger.info("Scheduler is already running.")
        return

    scheduler.add_job(
        updater.sync_favorites,
        "interval",
        minutes=settings.SYNC_INTERVAL_MINUTES,
        id="sync_favorites",
        replace_existing=True
    )

    scheduler.add_job(
        updater.check_updates_via_api,
        "interval",
        minutes=settings.SYNC_INTERVAL_MINUTES * 2, # Less frequent?
        id="check_api",
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started.")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped.")
