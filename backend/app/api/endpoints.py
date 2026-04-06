import asyncio
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, cast, String as SQLString
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.db.database import get_db
from app.db.models import Gallery, DownloadStatus
from app.core.config import settings
from app.core.output_template import OutputTemplateError
from app.services.downloader import downloader
from app.services.gallery_log import get_gallery_logs as load_gallery_logs
from app.services.maintenance import cleanup_legacy_state, get_legacy_state
from app.services.realtime import fallback_progress, format_sse_event, realtime_hub, utcnow_iso
from app.services.sync_state import (
    clear_all_failed_galleries,
    clear_failed_gallery,
    read_sync_state,
    reset_sync_state,
)
from app.services.updater import updater

router = APIRouter()


def serialize_gallery(gallery: Gallery, progress_map: dict[int, dict]) -> dict:
    status_value = gallery.status.value if hasattr(gallery.status, "value") else gallery.status
    progress = progress_map.get(gallery.gid)
    if not progress and status_value == DownloadStatus.PARTIAL.value:
        from app.core.native_crawler import NativeCrawler

        progress = NativeCrawler.build_partial_progress(
            gallery.gid,
            gallery.error_msg,
            output_dir=str(settings.DOWNLOAD_DIR),
        )

    return {
        "gid": gallery.gid,
        "token": gallery.token,
        "title": gallery.title,
        "status": status_value,
        "filecount": gallery.filecount,
        "posted": gallery.posted,
        "downloaded_at": gallery.downloaded_at,
        "favorited_at": gallery.favorited_at,
        "error_msg": gallery.error_msg,
        "parent_gid": gallery.parent_gid,
        "favcat": getattr(gallery, "favcat", None),
        "requested_quality": getattr(gallery, "requested_quality", None),
        "resolved_quality": getattr(gallery, "resolved_quality", None),
        "progress": progress or fallback_progress(status_value, gallery.error_msg),
    }

@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_db)):
    """
    Returns system status, running tasks, queue length.
    """
    queue_stmt = select(func.count()).select_from(Gallery).where(
        Gallery.status.in_([DownloadStatus.PENDING, DownloadStatus.OUTDATED])
    )
    queue_len = (await db.execute(queue_stmt)).scalar_one()

    active_stmt = select(func.count()).select_from(Gallery).where(
        Gallery.status == DownloadStatus.DOWNLOADING
    )
    active_downloads = (await db.execute(active_stmt)).scalar_one()
    sync_state = await read_sync_state()

    return {
        "downloader_running": downloader.is_running,
        "queue_len": queue_len,
        "active_downloads": active_downloads,
        "max_concurrent_downloads": downloader.max_concurrent,
        "failed_retry_count": len(sync_state.get("failed", {})),
        "last_sync_ts": sync_state.get("last_run_ts"),
        "sync_running": updater.sync_running,
        "sync_last_error": updater.last_sync_error,
    }

@router.get("/account")
async def get_account_info():
    """
    Returns E-Hentai account info including GP and Credits.
    """
    from app.core.client import eh_client
    info = await eh_client.get_account_info()
    return info

@router.get("/galleries")
async def list_galleries(
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(limit, 200))

    filters = []
    if status:
        filters.append(Gallery.status == status)

    if search:
        search_value = f"%{search.strip()}%"
        filters.append(
            or_(
                cast(Gallery.gid, SQLString).like(search_value),
                Gallery.title.ilike(search_value),
                Gallery.parent_gid.ilike(search_value),
            )
        )

    stmt = select(Gallery)
    count_stmt = select(func.count()).select_from(Gallery)

    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    stmt = stmt.order_by(Gallery.posted.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    galleries = result.scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    progress_map = await realtime_hub.get_gallery_progress_map()

    return {
        "items": [serialize_gallery(g, progress_map) for g in galleries],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/galleries/{gid}/logs")
async def get_gallery_log_entries(gid: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Gallery).where(Gallery.gid == gid)
    result = await db.execute(stmt)
    gallery = result.scalar_one_or_none()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")

    return {
        "gid": gallery.gid,
        "token": gallery.token,
        "title": gallery.title,
        "error_msg": gallery.error_msg,
        "requested_quality": getattr(gallery, "requested_quality", None),
        "resolved_quality": getattr(gallery, "resolved_quality", None),
        "logs": await load_gallery_logs(gallery.gid, gallery.token),
    }


@router.get("/events/downloads")
async def stream_download_events(request: Request):
    queue = await realtime_hub.subscribe()

    async def event_generator():
        try:
            yield format_sse_event("snapshot", await realtime_hub.build_snapshot())
            while True:
                if await request.is_disconnected():
                    break

                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    yield format_sse_event(message["event"], message["payload"])
                except asyncio.TimeoutError:
                    yield format_sse_event("heartbeat", {"updated_at": utcnow_iso()})
        finally:
            await realtime_hub.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.delete("/galleries/{gid}")
async def delete_gallery(gid: int, db: AsyncSession = Depends(get_db)):
    """Delete a gallery record only (keep files)."""
    stmt = select(Gallery).where(Gallery.gid == gid)
    result = await db.execute(stmt)
    gallery = result.scalar_one_or_none()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")

    settled = await downloader.cancel_and_wait(gid)
    if not settled:
        raise HTTPException(status_code=409, detail="Active download did not stop in time")

    await db.delete(gallery)
    await db.commit()
    await clear_failed_gallery(gid)
    await realtime_hub.clear_gallery(gid)
    return {"status": "Deleted", "gid": gid}

@router.delete("/galleries/{gid}/with-files")
async def delete_gallery_with_files(gid: int, db: AsyncSession = Depends(get_db)):
    """Delete gallery record, cancel active download, and delete downloaded files."""
    stmt = select(Gallery).where(Gallery.gid == gid)
    result = await db.execute(stmt)
    gallery = result.scalar_one_or_none()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")

    current_settings = settings.get_runtime_settings()
    was_active = downloader.is_active(gid)
    settled = await downloader.cancel_and_wait(gid)
    if not settled:
        raise HTTPException(status_code=409, detail="Active download did not stop in time")
    
    # Delete files
    deleted_files = downloader.delete_gallery_files(
        gid,
        known_paths=[gallery.download_path] if gallery.download_path else None,
        gallery=gallery,
        current_settings=current_settings,
    )
    
    # Delete record
    await db.delete(gallery)
    await db.commit()
    await clear_failed_gallery(gid)
    await realtime_hub.clear_gallery(gid)
    
    return {
        "status": "Deleted with files",
        "gid": gid,
        "was_downloading": was_active,
        "files_deleted": deleted_files
    }

@router.delete("/galleries")
async def delete_all_galleries(db: AsyncSession = Depends(get_db)):
    """Delete all galleries from the database."""
    from sqlalchemy import delete

    settled = await downloader.cancel_all_and_wait()
    if not settled:
        raise HTTPException(status_code=409, detail="Active downloads did not stop in time")

    stmt = delete(Gallery)
    await db.execute(stmt)
    await db.commit()
    await clear_all_failed_galleries()
    await realtime_hub.clear_all()
    return {"status": "All galleries deleted"}

@router.post("/galleries/{gid}/reset")
async def reset_gallery(gid: int, db: AsyncSession = Depends(get_db)):
    """Reset a gallery status to pending for re-download."""
    from app.db.models import DownloadStatus
    stmt = select(Gallery).where(Gallery.gid == gid)
    result = await db.execute(stmt)
    gallery = result.scalar_one_or_none()
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")

    settled = await downloader.cancel_and_wait(gid)
    if not settled:
        raise HTTPException(status_code=409, detail="Active download did not stop in time")

    gallery.status = DownloadStatus.PENDING
    gallery.error_msg = None
    gallery.requested_quality = None
    gallery.resolved_quality = None
    await db.commit()
    await clear_failed_gallery(gid)
    await realtime_hub.clear_gallery(gid)
    return {"status": "Reset", "gid": gid}

@router.post("/action/sync")
async def trigger_sync():
    """
    Manually trigger sync
    """
    started = updater.trigger_background_sync()
    if started:
        return {"status": "started", "message": "Sync started in background"}
    return {"status": "already_running", "message": "Sync is already running"}

@router.post("/action/reset-sync-state")
async def trigger_reset_sync_state():
    """
    Reset incremental sync cursors and failed retry queue.
    """
    await reset_sync_state()
    return {"status": "Sync state reset"}

from pydantic import BaseModel
from app.services.config_service import config_service
from app.db.models import DownloadStatus, Gallery, DownloadMode
from datetime import datetime

from typing import Optional

class SettingsUpdate(BaseModel):
    ipb_member_id: Optional[str] = None
    ipb_pass_hash: Optional[str] = None
    igneous: Optional[str] = None
    eh_domain: Optional[str] = None  # e-hentai.org or exhentai.org
    download_mode: Optional[str] = None
    archive_quality: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    allowed_telegram_ids: Optional[List[int]] = None
    telegram_notifications_enabled: Optional[bool] = None
    telegram_notification_recipients: Optional[List[int]] = None
    telegram_notify_download_completed: Optional[bool] = None
    telegram_notify_download_failed: Optional[bool] = None
    telegram_notify_download_partial: Optional[bool] = None
    telegram_notify_sync_completed: Optional[bool] = None
    telegram_notify_sync_failed: Optional[bool] = None
    telegram_notification_batch_window_seconds: Optional[int] = None
    telegram_notification_quiet_hours_enabled: Optional[bool] = None
    telegram_notification_quiet_hours_start: Optional[str] = None
    telegram_notification_quiet_hours_end: Optional[str] = None
    proxy_url: Optional[str] = None
    monitored_favcats: Optional[List[int]] = None
    fav_oldest_date: Optional[str] = None
    fav_date_timezone: Optional[str] = None
    auto_sync: Optional[bool] = None
    max_concurrent_downloads: Optional[int] = None
    max_retries: Optional[int] = None
    output_template: Optional[str] = None
    conflict_strategy: Optional[str] = None
    truncate_filenames: Optional[bool] = None
    filename_max_length: Optional[int] = None

class ManualDownload(BaseModel):
    url: str


class LegacyCleanupRequest(BaseModel):
    cleanup_app_config: bool = False
    cleanup_temp_cookies: bool = False
    cleanup_downloads_zip: bool = False

@router.get("/settings")
async def get_settings():
    return await config_service.get_public_settings()

@router.post("/settings")
async def update_settings(data: SettingsUpdate):
    updates = {field: getattr(data, field) for field in data.__fields_set__}
    from loguru import logger
    logger.info(f"Settings update received: {list(updates.keys())}")
    try:
        await config_service.update_settings(updates)
    except OutputTemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "Updated"}


@router.get("/maintenance/legacy-state")
async def get_maintenance_legacy_state():
    return await get_legacy_state()


@router.post("/maintenance/cleanup")
async def cleanup_maintenance_legacy_state(data: LegacyCleanupRequest):
    if not any(
        [
            data.cleanup_app_config,
            data.cleanup_temp_cookies,
            data.cleanup_downloads_zip,
        ]
    ):
        raise HTTPException(status_code=400, detail="No cleanup target selected")

    return await cleanup_legacy_state(
        cleanup_app_config=data.cleanup_app_config,
        cleanup_temp_cookies=data.cleanup_temp_cookies,
        cleanup_downloads_zip=data.cleanup_downloads_zip,
    )

@router.post("/download/manual")
async def manual_download(data: ManualDownload, db: AsyncSession = Depends(get_db)):
    """
    Manually add a gallery URL to the queue.
    URL format: https://e-hentai.org/g/{gid}/{token}/
    """
    try:
        from app.services.manual_queue import queue_manual_gallery

        result = await queue_manual_gallery(data.url, db)
        return {"status": result.status, "msg": result.message}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
