import asyncio
from functools import wraps
import os
import shutil
import time
from pathlib import Path
from sqlalchemy.future import select
from loguru import logger
from datetime import datetime, timezone
from typing import Dict, Optional, Set, List

from app.db.database import SessionLocal
from app.db.models import Gallery, DownloadStatus, DownloadMode
from app.core.archiver import GalleryArchiver
from app.core.archive_cache import ArchiveCache
from app.core.config import settings
from app.core.output_template import (
    OutputTemplateSettings,
    build_output_context,
    normalize_quality_preference,
    resolve_output_targets,
    with_temp_suffix,
)
from app.services.realtime import realtime_hub
from app.services.notification_service import notification_service
from app.services.sync_state import clear_failed_gallery, upsert_failed_gallery

class DownloaderService:
    def __init__(self):
        self.is_running = False
        self.queue_lock = asyncio.Lock()
        # Track active downloads by gid for cancellation
        self._active_downloads: Dict[int, asyncio.Task] = {}
        self._cancelled_gids: Set[int] = set()
        # Concurrent download control (archive mode only)
        self._max_concurrent: int = 3  # Default, can be changed via settings
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._active_count: int = 0

    @property
    def active_count(self) -> int:
        return self._active_count

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    async def _refresh_runtime_settings(self) -> dict:
        from app.services.config_service import config_service

        current_settings = await config_service.get_all_settings()
        new_max_concurrent = max(1, int(current_settings.get("max_concurrent_downloads", 3)))
        if self._semaphore is None:
            self._max_concurrent = new_max_concurrent
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
            logger.info(f"Max concurrent downloads set: {self._max_concurrent}")
        else:
            self._max_concurrent = new_max_concurrent
        return current_settings

    @staticmethod
    def _cleanup_archive_temp_file(temp_file: Path) -> None:
        try:
            if temp_file.exists():
                temp_file.unlink()
                logger.info(f"Removed archive temp file: {temp_file}")
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.warning(f"Failed to cleanup archive temp file {temp_file}: {exc}")

    async def start(self):
        if self.is_running:
            logger.info("Downloader Service is already running.")
            return

        self.is_running = True
        logger.info("Downloader Service started.")
        await self._refresh_runtime_settings()

        while self.is_running:
            try:
                await self._process_queue_concurrent()
            except Exception:
                logger.exception("Queue iteration failed; retrying without stopping the worker")
            await asyncio.sleep(2)  # Shorter sleep for responsiveness

    async def stop(self):
        self.is_running = False
        # Cancel all active downloads and wait for them to finish
        active_gids = [gid for gid, task in self._active_downloads.items() if not task.done()]
        if active_gids:
            logger.info(f"Stopping downloader: cancelling {len(active_gids)} active download(s)...")
            for gid in active_gids:
                self._cancelled_gids.add(gid)
                task = self._active_downloads.get(gid)
                if task and not task.done():
                    task.cancel()
            # Wait for all tasks to finish with a timeout
            tasks = [t for t in self._active_downloads.values() if not t.done()]
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=15.0)
                if pending:
                    logger.warning(f"{len(pending)} download task(s) did not finish within timeout")
        logger.info("Downloader Service stopped.")

    def cancel_download(self, gid: int) -> bool:
        """Mark a gid as cancelled. Returns True if was actively downloading."""
        self._cancelled_gids.add(gid)
        task = self._active_downloads.get(gid)
        if task and not task.done():
            asyncio.create_task(realtime_hub.emit_cancelled(gid))
            task.cancel()
            logger.info(f"Cancelled active download for gid={gid}")
            return True
        return False

    def is_active(self, gid: int) -> bool:
        task = self._active_downloads.get(gid)
        return bool(task and not task.done())

    async def wait_for_inactive(self, gid: int, timeout: float = 10.0, poll_interval: float = 0.1) -> bool:
        deadline = time.monotonic() + max(timeout, poll_interval)
        while time.monotonic() < deadline:
            if not self.is_active(gid):
                return True
            await asyncio.sleep(poll_interval)
        return not self.is_active(gid)

    async def cancel_and_wait(self, gid: int, timeout: float = 10.0) -> bool:
        was_active = self.cancel_download(gid)
        if not was_active:
            return True
        return await self.wait_for_inactive(gid, timeout=timeout)

    async def cancel_all_and_wait(self, timeout: float = 15.0) -> bool:
        active_gids = [gid for gid, task in self._active_downloads.items() if not task.done()]
        if not active_gids:
            return True

        for gid in active_gids:
            self.cancel_download(gid)

        deadline = time.monotonic() + max(timeout, 0.1)
        while time.monotonic() < deadline:
            if all(not self.is_active(gid) for gid in active_gids):
                return True
            await asyncio.sleep(0.1)
        return all(not self.is_active(gid) for gid in active_gids)

    def is_cancelled(self, gid: int) -> bool:
        """Check if a gid has been cancelled."""
        return gid in self._cancelled_gids

    def clear_cancelled(self, gid: int):
        """Clear cancelled flag for a gid."""
        self._cancelled_gids.discard(gid)

    async def _set_progress(
        self,
        gallery: Gallery,
        *,
        phase: str,
        percent: float,
        current: int | float | None = None,
        total: int | float | None = None,
        unit: str | None = None,
        detail: str = "",
    ) -> None:
        await realtime_hub.set_gallery_progress(
            gallery.gid,
            title=gallery.title,
            status=DownloadStatus.DOWNLOADING.value,
            requested_quality=getattr(gallery, "_requested_quality", None),
            resolved_quality=getattr(gallery, "_result_quality", None),
            progress={
                "phase": phase,
                "percent": percent,
                "current": current,
                "total": total,
                "unit": unit,
                "detail": detail,
            },
        )

    async def _emit_terminal_status(
        self,
        gallery: Gallery,
        *,
        status: str,
        error_msg: str | None = None,
        downloaded_at: datetime | None = None,
        detail: str | None = None,
        progress: dict | None = None,
        requested_quality: str | None = None,
        resolved_quality: str | None = None,
    ) -> None:
        resolved_progress = progress
        if resolved_progress is None:
            phase = "completed" if status == DownloadStatus.COMPLETED.value else status
            percent = 100 if phase == "completed" else 0
            resolved_progress = {
                "phase": phase,
                "percent": percent,
                "detail": detail or (error_msg or "下载完成"),
            }
        await realtime_hub.emit_gallery_status(
            gallery.gid,
            title=gallery.title,
            status=status,
            error_msg=error_msg,
            downloaded_at=downloaded_at.isoformat() if downloaded_at else None,
            requested_quality=requested_quality,
            resolved_quality=resolved_quality,
            progress=resolved_progress,
        )

    @staticmethod
    def find_gallery_files(gid: int) -> list[str]:
        """Find legacy-named gallery files under the downloads directory tree."""
        files: set[str] = set()
        download_dir = settings.DOWNLOAD_DIR
        if not download_dir.exists():
            return []

        prefix = f"[{gid}]"
        for candidate in download_dir.rglob("*"):
            if candidate.is_file() and candidate.name.startswith(prefix):
                files.add(str(candidate))

        return sorted(files)

    @classmethod
    def _collect_expected_gallery_paths(
        cls,
        gallery: Optional[Gallery],
        current_settings: Optional[dict] = None,
    ) -> set[str]:
        if gallery is None:
            return set()

        runtime_settings = current_settings or settings.get_runtime_settings()
        output_settings = cls._build_output_template_settings(runtime_settings)
        candidate_qualities = [
            getattr(gallery, "resolved_quality", None),
            getattr(gallery, "requested_quality", None),
            runtime_settings.get("archive_quality"),
            settings.ARCHIVE_QUALITY,
            "original",
            "native",
        ]
        seen: set[str] = set()
        collected: set[str] = set()
        for quality in candidate_qualities:
            normalized_quality = normalize_quality_preference(quality)
            if normalized_quality in seen:
                continue
            seen.add(normalized_quality)
            try:
                final_path, partial_path = resolve_output_targets(
                    settings=output_settings,
                    context=cls._build_output_context(
                        gallery,
                        quality=normalized_quality,
                        downloaded_at=gallery.downloaded_at,
                    ),
                )
            except Exception as exc:
                logger.debug(f"Failed to resolve output template for gid={gallery.gid}: {exc}")
                continue

            collected.update(
                {
                    str(final_path),
                    str(partial_path),
                    str(with_temp_suffix(final_path)),
                }
            )
        return collected

    @classmethod
    def delete_gallery_files(
        cls,
        gid: int,
        known_paths: Optional[List[str]] = None,
        gallery: Optional[Gallery] = None,
        current_settings: Optional[dict] = None,
    ) -> int:
        """Delete all files related to a gallery. Returns count of deleted files."""
        files = set(cls.find_gallery_files(gid))
        for path in known_paths or []:
            if path:
                files.add(path)
        # Never recompute a deletion target from today's template: it may belong
        # to another gallery after settings or titles have changed.
        files.update(str(settings.DATA_DIR / "archive_temp" / f"{gid}{suffix}") for suffix in (".download", ".json"))
        deleted = 0
        for f in sorted(files):
            try:
                os.remove(f)
                logger.info(f"Deleted file: {f}")
                deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete {f}: {e}")
        try:
            from app.core.native_crawler import NativeCrawler

            deleted += NativeCrawler.cleanup_resume_artifacts(gid, output_dir=str(settings.DOWNLOAD_DIR))
        except Exception as e:
            logger.warning(f"Failed to cleanup resume artifacts for {gid}: {e}")
        return deleted

    @staticmethod
    def _build_output_template_settings(current_settings: dict) -> OutputTemplateSettings:
        return OutputTemplateSettings(
            template=current_settings.get("output_template") or settings.OUTPUT_TEMPLATE,
            conflict_strategy=current_settings.get("conflict_strategy") or settings.CONFLICT_STRATEGY,
            truncate_enabled=bool(current_settings.get("truncate_filenames", settings.TRUNCATE_FILENAMES)),
            max_length=int(current_settings.get("filename_max_length", settings.FILENAME_MAX_LENGTH)),
            timezone_mode=current_settings.get("fav_date_timezone") or settings.FAV_DATE_TIMEZONE,
            base_dir=settings.BASE_DIR,
        )

    @staticmethod
    def _build_output_context(
        gallery: Gallery,
        *,
        quality: str,
        downloaded_at: Optional[datetime],
    ) -> dict:
        return build_output_context(
            gid=gallery.gid,
            title=gallery.title,
            jpn_title=gallery.title_jpn,
            category=gallery.category,
            uploader=gallery.uploader,
            filecount=gallery.filecount,
            quality=quality,
            parent_gid=gallery.parent_gid,
            downloaded_at=downloaded_at,
            favorited_at=gallery.favorited_at,
            fav=gallery.favcat,
        )

    @staticmethod
    def _quality_label(value: Optional[str]) -> Optional[str]:
        if value == "original":
            return "原图"
        if value == "native":
            return "展示图"
        return None

    @classmethod
    def _quality_summary(
        cls,
        requested_quality: Optional[str],
        resolved_quality: Optional[str],
    ) -> Optional[str]:
        resolved_label = cls._quality_label(resolved_quality)
        if not resolved_label:
            return None
        if requested_quality == "original" and resolved_quality == "native":
            return f"最终质量：{resolved_label}（原图不可用，已自动降级）"
        return f"最终质量：{resolved_label}"

    @classmethod
    def _append_quality_summary(
        cls,
        base_text: Optional[str],
        requested_quality: Optional[str],
        resolved_quality: Optional[str],
    ) -> Optional[str]:
        summary = cls._quality_summary(requested_quality, resolved_quality)
        if not summary:
            return base_text
        if not base_text:
            return summary
        if summary in base_text:
            return base_text
        separator = "；" if "：" in base_text or "，" in base_text else "，"
        return f"{base_text}{separator}{summary}"

    async def _notify_download_outcome(
        self,
        gallery: Gallery,
        *,
        status: str,
        requested_quality: Optional[str],
        resolved_quality: Optional[str],
        downloaded_at: Optional[datetime] = None,
        error_msg: Optional[str] = None,
        progress: Optional[dict] = None,
    ) -> None:
        try:
            if status == DownloadStatus.COMPLETED.value:
                await notification_service.notify_download_completed(
                    gallery,
                    requested_quality=requested_quality,
                    resolved_quality=resolved_quality,
                    downloaded_at=downloaded_at,
                )
            elif status == DownloadStatus.PARTIAL.value:
                await notification_service.notify_download_partial(
                    gallery,
                    error_msg=error_msg,
                    requested_quality=requested_quality,
                    resolved_quality=resolved_quality,
                    progress=progress,
                )
            elif status == DownloadStatus.FAILED.value:
                await notification_service.notify_download_failed(
                    gallery,
                    error_msg=error_msg,
                    requested_quality=requested_quality,
                    resolved_quality=resolved_quality,
                )
        except Exception as exc:
            logger.warning(f"Failed to send Telegram download notification for {gallery.gid}: {exc}")

    def serialize_queue_mutation(self, handler):
        @wraps(handler)
        async def wrapped(*args, **kwargs):
            async with self.queue_lock:
                return await handler(*args, **kwargs)
        return wrapped

    async def _process_queue_concurrent(self):
        async with self.queue_lock:
            await self._dispatch_queue()

    async def _dispatch_queue(self):
        """Process downloads with concurrency support for archive mode."""
        current_settings = await self._refresh_runtime_settings()
        mode = current_settings.get("download_mode") or settings.DOWNLOAD_MODE

        # Only archive mode supports concurrent gallery downloads
        if mode == DownloadMode.ARCHIVE or mode == "archive":
            # Check how many we can start
            available_slots = self._max_concurrent - len(self._active_downloads)
            if available_slots <= 0:
                return

            # Get pending galleries
            async with SessionLocal() as session:
                stmt = select(Gallery).where(
                    Gallery.status.in_([DownloadStatus.PENDING, DownloadStatus.OUTDATED]),
                    Gallery.gid.not_in(list(self._active_downloads)),
                ).order_by(Gallery.priority.desc(), Gallery.created_at.asc()).limit(available_slots)

                result = await session.execute(stmt)
                galleries = result.scalars().all()

                if not galleries:
                    return

                # Mark them as downloading
                for g in galleries:
                    g.status = DownloadStatus.DOWNLOADING
                await session.commit()

                # Start concurrent downloads; revert status on task creation failure
                for g in galleries:
                    self.clear_cancelled(g.gid)
                    try:
                        task = asyncio.create_task(self._download_with_semaphore(g, mode))
                    except Exception as exc:
                        logger.error(f"Failed to create download task for gid={g.gid}: {exc}")
                        g.status = DownloadStatus.PENDING
                        await session.commit()
                        continue
                    self._active_downloads[g.gid] = task
                    task.add_done_callback(lambda done, gid=g.gid: self._forget_task(gid, done))
        else:
            # Sequential mode for native_crawl
            # Only process if no active downloads (truly sequential)
            if self._active_count > 0:
                return
            await self._process_queue()

    def _forget_task(self, gid, task):
        if self._active_downloads.get(gid) is task:
            self._active_downloads.pop(gid, None)

    async def _download_with_semaphore(self, gallery: Gallery, mode: str):
        """Download a gallery with semaphore control."""
        self._active_count += 1
        try:
            from app.services.gallery_log import append_gallery_log
            await self._set_progress(
                gallery,
                phase="preparing",
                percent=2,
                detail=f"准备启动下载 ({mode})",
            )
            await append_gallery_log(gallery.gid, gallery.token, f"开始下载 (模式: {mode})")

            success = await self._download_gallery(gallery, mode)
            result_status = getattr(gallery, "_result_status", None) or (
                DownloadStatus.COMPLETED.value if success else DownloadStatus.FAILED.value
            )
            result_progress = getattr(gallery, "_result_progress", None)
            result_detail = getattr(gallery, "_result_detail", None)
            result_downloaded_at = getattr(gallery, "_result_downloaded_at", None)
            result_requested_quality = getattr(gallery, "_requested_quality", None)
            result_resolved_quality = getattr(gallery, "_result_quality", None)

            async with SessionLocal() as session:
                async with session.begin():
                    g = await session.get(Gallery, (gallery.gid, gallery.token))
                    if g:
                        g.requested_quality = result_requested_quality
                        g.resolved_quality = result_resolved_quality
                        if result_status == DownloadStatus.COMPLETED.value:
                            g.status = DownloadStatus.COMPLETED
                            g.downloaded_at = result_downloaded_at or datetime.now(timezone.utc)
                            g.download_path = getattr(gallery, "download_path", None)
                            g.error_msg = None
                            g.retry_count = 0
                            await append_gallery_log(
                                gallery.gid,
                                gallery.token,
                                self._append_quality_summary(
                                    "下载完成",
                                    result_requested_quality,
                                    result_resolved_quality,
                                ) or "下载完成",
                                "success",
                                session=session,
                            )
                            await clear_failed_gallery(g.gid, session=session)
                        elif result_status == DownloadStatus.PARTIAL.value:
                            g.status = DownloadStatus.PARTIAL
                            g.download_path = getattr(gallery, "download_path", None)
                            g.retry_count += 1
                            g.error_msg = gallery.error_msg or g.error_msg or "部分下载完成，存在缺页"
                            partial_detail = self._append_quality_summary(
                                result_detail or f"部分下载完成: {g.error_msg}",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await append_gallery_log(
                                gallery.gid,
                                gallery.token,
                                partial_detail or f"部分下载完成: {g.error_msg}",
                                "warning",
                                session=session,
                            )
                            if not self.is_cancelled(g.gid):
                                await upsert_failed_gallery(g, session=session)
                        elif result_status == "cancelled" or self.is_cancelled(g.gid):
                            g.status = DownloadStatus.PENDING
                            g.error_msg = None
                            await append_gallery_log(
                                gallery.gid,
                                gallery.token,
                                "下载已取消",
                                "warning",
                                session=session,
                            )
                        else:
                            g.status = DownloadStatus.FAILED
                            g.retry_count += 1
                            g.error_msg = gallery.error_msg or g.error_msg or "Download failed"
                            failure_detail = self._append_quality_summary(
                                f"下载失败: {g.error_msg}",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await append_gallery_log(
                                gallery.gid,
                                gallery.token,
                                failure_detail or f"下载失败: {g.error_msg}",
                                "error",
                                session=session,
                            )
                            if not self.is_cancelled(g.gid):
                                await upsert_failed_gallery(g, session=session)
                    await session.commit()
                    if g:
                        if result_status == DownloadStatus.COMPLETED.value:
                            completion_detail = self._append_quality_summary(
                                "下载完成",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await self._emit_terminal_status(
                                g,
                                status=DownloadStatus.COMPLETED.value,
                                downloaded_at=g.downloaded_at,
                                detail=completion_detail or "下载完成",
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                            await self._notify_download_outcome(
                                g,
                                status=DownloadStatus.COMPLETED.value,
                                downloaded_at=g.downloaded_at,
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                        elif result_status == DownloadStatus.PARTIAL.value:
                            partial_detail = self._append_quality_summary(
                                result_detail or g.error_msg or "部分下载完成，等待补抓",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await self._emit_terminal_status(
                                g,
                                status=DownloadStatus.PARTIAL.value,
                                error_msg=g.error_msg,
                                detail=partial_detail or g.error_msg or "部分下载完成，等待补抓",
                                progress={
                                    **result_progress,
                                    "detail": partial_detail or result_progress.get("detail") or "",
                                } if result_progress else None,
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                            await self._notify_download_outcome(
                                g,
                                status=DownloadStatus.PARTIAL.value,
                                error_msg=g.error_msg,
                                progress=result_progress,
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                        elif result_status == "cancelled" or self.is_cancelled(g.gid):
                            await realtime_hub.emit_cancelled(g.gid, title=g.title)
                        else:
                            failure_detail = self._append_quality_summary(
                                g.error_msg or "下载失败",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await self._emit_terminal_status(
                                g,
                                status=DownloadStatus.FAILED.value,
                                error_msg=g.error_msg,
                                detail=failure_detail or g.error_msg or "下载失败",
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                            await self._notify_download_outcome(
                                g,
                                status=DownloadStatus.FAILED.value,
                                error_msg=g.error_msg,
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
        except asyncio.CancelledError:
            from app.services.gallery_log import append_gallery_log
            await append_gallery_log(gallery.gid, gallery.token, "下载已取消", "warning")
            await realtime_hub.clear_gallery(gallery.gid)
            raise
        except Exception as e:
            logger.error(f"Error in concurrent download {gallery.gid}: {e}")
            from app.services.gallery_log import append_gallery_log
            await append_gallery_log(gallery.gid, gallery.token, f"下载异常: {str(e)}", "error")
            async with SessionLocal() as session:
                async with session.begin():
                    g = await session.get(Gallery, (gallery.gid, gallery.token))
                    if g:
                        g.status = DownloadStatus.FAILED
                        g.error_msg = str(e)
                        g.requested_quality = getattr(gallery, "_requested_quality", None)
                        g.resolved_quality = getattr(gallery, "_result_quality", None)
                        if not self.is_cancelled(g.gid):
                            await upsert_failed_gallery(g, session=session)
                    await session.commit()
                    if g:
                        await self._emit_terminal_status(
                            g,
                            status=DownloadStatus.FAILED.value,
                            error_msg=str(e),
                            detail=self._append_quality_summary(
                                str(e),
                                getattr(gallery, "_requested_quality", None),
                                getattr(gallery, "_result_quality", None),
                            ) or str(e),
                            requested_quality=getattr(gallery, "_requested_quality", None),
                            resolved_quality=getattr(gallery, "_result_quality", None),
                        )
                        await self._notify_download_outcome(
                            g,
                            status=DownloadStatus.FAILED.value,
                            error_msg=str(e),
                            requested_quality=getattr(gallery, "_requested_quality", None),
                            resolved_quality=getattr(gallery, "_result_quality", None),
                        )
        finally:
            self._active_count = max(0, self._active_count - 1)
            self._active_downloads.pop(gallery.gid, None)

    async def _process_queue(self):
        async with SessionLocal() as session:
            # multiple sessions? Using context manager ensures close.
            # transaction?
            async with session.begin():
                # Find one pending task
                stmt = select(Gallery).where(
                    Gallery.status.in_([DownloadStatus.PENDING, DownloadStatus.OUTDATED])
                ).order_by(Gallery.priority.desc(), Gallery.created_at.asc()).limit(1)

                result = await session.execute(stmt)
                gallery = result.scalar_one_or_none()

                if not gallery:
                    return

                # Lock it
                gallery.status = DownloadStatus.DOWNLOADING
                await session.commit()

                gid = gallery.gid

                # Clear any stale cancelled flag from previous deletion
                self.clear_cancelled(gid)

        task = asyncio.create_task(self._run_sequential_gallery(gallery))
        self._active_downloads[gid] = task
        def cleanup(done):
            if self._active_downloads.get(gid) is done:
                self._active_downloads.pop(gid, None)
        task.add_done_callback(cleanup)

    async def _run_sequential_gallery(self, gallery: Gallery):
        gid = gallery.gid
        token = gallery.token

        # Process outside of db transaction
        self._active_count += 1  # Track that we're downloading
        try:
            from app.services.config_service import config_service
            from app.services.gallery_log import append_gallery_log
            current_settings = await config_service.get_all_settings()
            mode = current_settings.get("download_mode") or settings.DOWNLOAD_MODE
            logger.info(f"Using download mode: {mode} for gallery {gid}")
            await self._set_progress(
                gallery,
                phase="preparing",
                percent=2,
                detail=f"准备启动下载 ({mode})",
            )
            await append_gallery_log(gid, token, f"开始下载 (模式: {mode})")

            success = await self._download_gallery(gallery, mode)
            result_status = getattr(gallery, "_result_status", None) or (
                DownloadStatus.COMPLETED.value if success else DownloadStatus.FAILED.value
            )
            result_progress = getattr(gallery, "_result_progress", None)
            result_detail = getattr(gallery, "_result_detail", None)
            result_downloaded_at = getattr(gallery, "_result_downloaded_at", None)
            result_requested_quality = getattr(gallery, "_requested_quality", None)
            result_resolved_quality = getattr(gallery, "_result_quality", None)

            async with SessionLocal() as session:
                async with session.begin():
                    g = await session.get(Gallery, (gallery.gid, gallery.token)) # composite key query?
                    # SQLAlchemy composite pk get: session.get(Gallery, (gid, token))
                    if g:
                        g.requested_quality = result_requested_quality
                        g.resolved_quality = result_resolved_quality
                        if result_status == DownloadStatus.COMPLETED.value:
                            g.status = DownloadStatus.COMPLETED
                            g.downloaded_at = result_downloaded_at or datetime.now(timezone.utc)
                            g.download_path = getattr(gallery, "download_path", None)
                            g.error_msg = None
                            g.retry_count = 0
                            await append_gallery_log(
                                gid,
                                token,
                                self._append_quality_summary(
                                    "下载完成",
                                    result_requested_quality,
                                    result_resolved_quality,
                                ) or "下载完成",
                                "success",
                                session=session,
                            )
                            await clear_failed_gallery(g.gid, session=session)
                        elif result_status == DownloadStatus.PARTIAL.value:
                            g.status = DownloadStatus.PARTIAL
                            g.download_path = getattr(gallery, "download_path", None)
                            g.retry_count += 1
                            g.error_msg = gallery.error_msg or g.error_msg or "部分下载完成，存在缺页"
                            partial_detail = self._append_quality_summary(
                                result_detail or f"部分下载完成: {g.error_msg}",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await append_gallery_log(
                                gid,
                                token,
                                partial_detail or f"部分下载完成: {g.error_msg}",
                                "warning",
                                session=session,
                            )
                            if not self.is_cancelled(g.gid):
                                await upsert_failed_gallery(g, session=session)
                        elif result_status == "cancelled" or self.is_cancelled(g.gid):
                            g.status = DownloadStatus.PENDING
                            g.error_msg = None
                            await append_gallery_log(
                                gid,
                                token,
                                "下载已取消",
                                "warning",
                                session=session,
                            )
                        else:
                            g.status = DownloadStatus.FAILED
                            # Retry logic could go here
                            g.retry_count += 1
                            g.error_msg = gallery.error_msg or g.error_msg or "Download failed"
                            failure_detail = self._append_quality_summary(
                                f"下载失败: {g.error_msg}",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await append_gallery_log(
                                gid,
                                token,
                                failure_detail or f"下载失败: {g.error_msg}",
                                "error",
                                session=session,
                            )
                            if not self.is_cancelled(g.gid):
                                await upsert_failed_gallery(g, session=session)
                    await session.commit()
                    if g:
                        if result_status == DownloadStatus.COMPLETED.value:
                            completion_detail = self._append_quality_summary(
                                "下载完成",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await self._emit_terminal_status(
                                g,
                                status=DownloadStatus.COMPLETED.value,
                                downloaded_at=g.downloaded_at,
                                detail=completion_detail or "下载完成",
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                            await self._notify_download_outcome(
                                g,
                                status=DownloadStatus.COMPLETED.value,
                                downloaded_at=g.downloaded_at,
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                        elif result_status == DownloadStatus.PARTIAL.value:
                            partial_detail = self._append_quality_summary(
                                result_detail or g.error_msg or "部分下载完成，等待补抓",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await self._emit_terminal_status(
                                g,
                                status=DownloadStatus.PARTIAL.value,
                                error_msg=g.error_msg,
                                detail=partial_detail or g.error_msg or "部分下载完成，等待补抓",
                                progress={
                                    **result_progress,
                                    "detail": partial_detail or result_progress.get("detail") or "",
                                } if result_progress else None,
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                            await self._notify_download_outcome(
                                g,
                                status=DownloadStatus.PARTIAL.value,
                                error_msg=g.error_msg,
                                progress=result_progress,
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                        elif result_status == "cancelled" or self.is_cancelled(g.gid):
                            await realtime_hub.emit_cancelled(g.gid, title=g.title)
                        else:
                            failure_detail = self._append_quality_summary(
                                g.error_msg or "下载失败",
                                result_requested_quality,
                                result_resolved_quality,
                            )
                            await self._emit_terminal_status(
                                g,
                                status=DownloadStatus.FAILED.value,
                                error_msg=g.error_msg,
                                detail=failure_detail or g.error_msg or "下载失败",
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )
                            await self._notify_download_outcome(
                                g,
                                status=DownloadStatus.FAILED.value,
                                error_msg=g.error_msg,
                                requested_quality=result_requested_quality,
                                resolved_quality=result_resolved_quality,
                            )

        except asyncio.CancelledError:
            from app.services.gallery_log import append_gallery_log
            await append_gallery_log(gid, token, "下载已取消", "warning")
            await realtime_hub.clear_gallery(gid)
            raise
        except Exception as e:
            logger.error(f"Error processing {gid}: {e}")
            from app.services.gallery_log import append_gallery_log
            await append_gallery_log(gid, token, f"下载异常: {str(e)}", "error")
            async with SessionLocal() as session:
               async with session.begin():
                    g = await session.get(Gallery, (gid, token))
                    if g:
                        g.status = DownloadStatus.FAILED
                        g.error_msg = str(e)
                        g.requested_quality = getattr(gallery, "_requested_quality", None)
                        g.resolved_quality = getattr(gallery, "_result_quality", None)
                        if not self.is_cancelled(g.gid):
                            await upsert_failed_gallery(g, session=session)
                    await session.commit()
                    if g:
                        await self._emit_terminal_status(
                            g,
                            status=DownloadStatus.FAILED.value,
                            error_msg=str(e),
                            detail=self._append_quality_summary(
                                str(e),
                                getattr(gallery, "_requested_quality", None),
                                getattr(gallery, "_result_quality", None),
                            ) or str(e),
                            requested_quality=getattr(gallery, "_requested_quality", None),
                            resolved_quality=getattr(gallery, "_result_quality", None),
                        )
                        await self._notify_download_outcome(
                            g,
                            status=DownloadStatus.FAILED.value,
                            error_msg=str(e),
                            requested_quality=getattr(gallery, "_requested_quality", None),
                            resolved_quality=getattr(gallery, "_result_quality", None),
                        )
        finally:
            self._active_count = max(0, self._active_count - 1)
            self._active_downloads.pop(gid, None)

    async def _download_gallery(self, gallery: Gallery, mode: str) -> bool:
        """
        Executes download based on mode. Returns True if success.
        """
        gallery._result_status = None
        gallery._result_progress = None
        gallery._result_detail = None
        gallery._result_downloaded_at = None
        gallery._requested_quality = None
        gallery._result_quality = None

        try:
            from app.services.config_service import config_service

            current_settings = await config_service.get_all_settings()
            quality_preference = normalize_quality_preference(
                current_settings.get("archive_quality") or settings.ARCHIVE_QUALITY
            )
            gallery._requested_quality = quality_preference
            output_template_settings = self._build_output_template_settings(current_settings)
            # Validate destination before making a paid archive request or fetching images.
            resolve_output_targets(settings=output_template_settings, context=self._build_output_context(
                gallery, quality=quality_preference, downloaded_at=datetime.now(timezone.utc)))

            if mode == DownloadMode.ARCHIVE or mode == "archive":
                if not gallery.token:
                    raise Exception("No token for archive download")

                logger.info(f"Starting archive download for gid={gallery.gid}")
                temp_root = settings.DATA_DIR / "archive_temp"
                temp_root.mkdir(parents=True, exist_ok=True)
                temp_file = temp_root / f"{gallery.gid}.download"

                cache = ArchiveCache(temp_file, gallery.gid, gallery.token, quality_preference)
                cached = await asyncio.to_thread(cache.valid)
                if temp_file.exists() and not cached:
                    logger.warning(f"Removing stale temp archive before download: {temp_file}")
                    self._cleanup_archive_temp_file(temp_file)
                    cache.forget()

                is_cancelled = lambda: self.is_cancelled(gallery.gid)
                progress_callback = lambda **payload: self._set_progress(gallery, **payload)
                max_retries = int(current_settings.get("max_retries", 3))
                refresh_attempt = 0
                max_refresh_attempts = 1
                success = cached

                while not success:
                    dl_url, size = await GalleryArchiver.prepare_and_poll(
                        gid=gallery.gid,
                        token=gallery.token,
                        quality=quality_preference,
                        is_cancelled=is_cancelled,
                        progress_callback=progress_callback,
                    )

                    if self.is_cancelled(gallery.gid):
                        logger.info(f"Archive download cancelled for {gallery.gid}")
                        gallery._result_status = "cancelled"
                        gallery._result_detail = "下载已取消"
                        self._cleanup_archive_temp_file(temp_file)
                        return False

                    if not dl_url:
                        logger.warning(f"Archiver failed for {gallery.gid}, no fallback downloader is configured")
                        gallery.error_msg = "未能获取归档下载链接"
                        return False

                    logger.info(f"Got download URL for {gallery.gid}, size={size}")
                    result = await GalleryArchiver.download_file(
                        dl_url,
                        str(temp_file),
                        is_cancelled=is_cancelled,
                        max_retries=max_retries,
                        progress_callback=progress_callback,
                    )
                    success = result.success
                    if result.cancelled:
                        gallery._result_status = "cancelled"
                        gallery._result_detail = "下载已取消"
                        gallery.error_msg = None
                        gallery._result_quality = quality_preference
                        self._cleanup_archive_temp_file(temp_file)
                        return False
                    if success:
                        await asyncio.to_thread(cache.mark_complete)
                        break

                    if temp_file.exists():
                        self._cleanup_archive_temp_file(temp_file)

                    if (
                        result.should_refresh_url
                        and refresh_attempt < max_refresh_attempts
                        and not self.is_cancelled(gallery.gid)
                    ):
                        refresh_attempt += 1
                        logger.warning(
                            f"Archive download URL may have expired for gid={gallery.gid}; "
                            f"re-requesting ({refresh_attempt}/{max_refresh_attempts})"
                        )
                        from app.services.gallery_log import append_gallery_log

                        await append_gallery_log(
                            gallery.gid,
                            gallery.token,
                            "归档链接疑似失效，正在重新申请下载链接",
                            "warning",
                        )
                        await self._set_progress(
                            gallery,
                            phase="polling",
                            percent=12,
                            detail="归档链接疑似失效，正在重新申请",
                        )
                        continue

                    if result.error_msg:
                        gallery.error_msg = result.error_msg
                    break

                if success and temp_file.exists():
                    await self._set_progress(
                        gallery,
                        phase="packaging",
                        percent=99,
                        detail="移动归档文件到目标位置",
                    )
                    completed_at = datetime.now(timezone.utc)
                    final_file, partial_file = resolve_output_targets(
                        settings=output_template_settings,
                        context=self._build_output_context(
                            gallery,
                            quality=quality_preference,
                            downloaded_at=completed_at,
                        ),
                    )
                    if output_template_settings.conflict_strategy == "overwrite":
                        for conflict_path in (final_file, partial_file, with_temp_suffix(final_file)):
                            if conflict_path.exists():
                                conflict_path.unlink()
                    shutil.move(str(temp_file), str(final_file))
                    cache.forget()
                    gallery._result_status = DownloadStatus.COMPLETED.value
                    gallery._result_detail = "下载完成"
                    gallery._result_downloaded_at = completed_at
                    gallery._result_quality = quality_preference
                    gallery.download_path = str(final_file)
                    logger.info(f"Archive download completed: {final_file}")
                    return True
                else:
                    if self.is_cancelled(gallery.gid):
                        self._cleanup_archive_temp_file(temp_file)
                    if not gallery.error_msg:
                        gallery.error_msg = "归档下载失败"
                    gallery._result_quality = quality_preference
                    logger.error(f"Archive download failed for {gallery.gid}")
                    return False

            elif mode == DownloadMode.NATIVE_CRAWL or mode == "native_crawl":
                from app.core.native_crawler import NativeCrawler
                domain = current_settings.get("eh_domain") or settings.EH_DOMAIN
                url = f"https://{domain}/g/{gallery.gid}/{gallery.token}/"

                max_images = int(current_settings.get("max_concurrent_downloads", 3))
                max_retries = int(current_settings.get("max_retries", 3))

                result = await NativeCrawler.download(
                    url=url,
                    output_dir=str(settings.DOWNLOAD_DIR),
                    is_cancelled=lambda: self.is_cancelled(gallery.gid),
                    max_concurrent_images=max_images,
                    max_retries=max_retries,
                    progress_callback=lambda **payload: self._set_progress(gallery, **payload),
                    preferred_quality=quality_preference,
                    output_template_settings=output_template_settings,
                    output_context=self._build_output_context(
                        gallery,
                        quality=quality_preference,
                        downloaded_at=None,
                    ),
                )
                gallery.download_path = result.file_path
                gallery._result_quality = result.quality or quality_preference
                if result.success:
                    gallery._result_status = DownloadStatus.COMPLETED.value
                    gallery._result_detail = "下载完成"
                    gallery._result_downloaded_at = result.completed_at or datetime.now(timezone.utc)
                    return True

                partial_progress = None
                if result.file_path and ".partial" in os.path.basename(result.file_path):
                    partial_progress = NativeCrawler.build_partial_progress(
                        gallery.gid,
                        result.error,
                        output_dir=str(settings.DOWNLOAD_DIR),
                    )

                if partial_progress:
                    gallery._result_status = DownloadStatus.PARTIAL.value
                    gallery._result_progress = partial_progress
                    gallery._result_detail = partial_progress.get("detail")
                    if not gallery.error_msg:
                        gallery.error_msg = result.error or "部分下载完成，存在缺页"
                else:
                    gallery._result_status = DownloadStatus.FAILED.value
                    if not gallery.error_msg:
                        gallery.error_msg = result.error or "原生爬虫下载失败"
                return result.success

        except Exception as e:
            logger.error(f"Download failed for {gallery.gid}: {e}")
            gallery._result_status = DownloadStatus.FAILED.value
            if not getattr(gallery, "_result_quality", None):
                gallery._result_quality = getattr(gallery, "_requested_quality", None)
            gallery.error_msg = str(e)
            return False

        return False

downloader = DownloaderService()
