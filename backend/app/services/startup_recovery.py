from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from sqlalchemy import select

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import DownloadMode, DownloadStatus, Gallery
from app.services.gallery_log import append_gallery_log


@dataclass
class RecoverySummary:
    recovered_total: int = 0
    native_resume_total: int = 0
    archive_requeue_total: int = 0


class StartupRecoveryService:
    @staticmethod
    def _normalize_mode(value: str | None) -> str:
        mode = str(value or settings.DOWNLOAD_MODE).strip()
        if mode == DownloadMode.NATIVE_CRAWL or mode == DownloadMode.NATIVE_CRAWL.value:
            return DownloadMode.NATIVE_CRAWL.value
        return DownloadMode.ARCHIVE.value

    @staticmethod
    def _archive_temp_exists(gid: int) -> bool:
        temp_file = settings.DATA_DIR / "archive_temp" / f"{gid}.download"
        return temp_file.exists()

    @staticmethod
    def _build_recovery_message(gallery: Gallery) -> tuple[str, bool]:
        mode = StartupRecoveryService._normalize_mode(gallery.download_mode)

        if mode == DownloadMode.NATIVE_CRAWL.value:
            from app.core.native_crawler import NativeCrawler

            resume_state = NativeCrawler.describe_resume_artifacts(gallery.gid)
            if resume_state["has_artifacts"]:
                downloaded_files = int(resume_state.get("downloaded_files") or 0)
                if downloaded_files > 0:
                    return (
                        f"检测到上次运行中断，已保留 {downloaded_files} 张图片的断点数据，任务恢复后将继续补抓",
                        True,
                    )
                if resume_state.get("partial_zip_exists"):
                    return ("检测到上次运行中断，已保留部分归档，任务恢复后将继续补抓", True)
                return ("检测到上次运行中断，已保留断点数据，任务恢复后将继续补抓", True)

            return ("检测到上次运行中断，已重新排队原生爬虫任务", False)

        if StartupRecoveryService._archive_temp_exists(gallery.gid):
            return ("检测到上次运行中断，将校验临时归档后恢复下载", False)

        return ("检测到上次运行中断，已重新排队下载任务", False)

    @staticmethod
    async def recover_interrupted_downloads() -> RecoverySummary:
        summary = RecoverySummary()

        async with SessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(Gallery).where(Gallery.status == DownloadStatus.DOWNLOADING)
                )
                galleries = result.scalars().all()

                for gallery in galleries:
                    message, has_resume_data = StartupRecoveryService._build_recovery_message(gallery)
                    gallery.status = DownloadStatus.PENDING
                    gallery.error_msg = message
                    gallery.resolved_quality = None

                    await append_gallery_log(
                        gallery.gid,
                        gallery.token,
                        message,
                        "warning",
                        session=session,
                    )

                    summary.recovered_total += 1
                    if StartupRecoveryService._normalize_mode(gallery.download_mode) == DownloadMode.NATIVE_CRAWL.value:
                        if has_resume_data:
                            summary.native_resume_total += 1
                    else:
                        summary.archive_requeue_total += 1

        if summary.recovered_total:
            logger.warning(
                "Recovered interrupted downloads on startup: "
                f"total={summary.recovered_total}, "
                f"native_resume={summary.native_resume_total}, "
                f"archive_requeue={summary.archive_requeue_total}"
            )
        else:
            logger.info("No interrupted downloads needed recovery on startup.")

        return summary


startup_recovery_service = StartupRecoveryService()
