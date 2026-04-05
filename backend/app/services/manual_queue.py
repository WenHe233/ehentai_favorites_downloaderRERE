from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.parser import EHParser
from app.db.models import DownloadMode, DownloadStatus, Gallery


@dataclass
class ManualQueueResult:
    status: str
    message: str
    gid: int
    token: str
    title: str
    has_newer_version: bool = False


async def _get_runtime_download_mode() -> str:
    try:
        from app.services.config_service import config_service

        runtime_settings = await config_service.get_all_settings()
        return str(runtime_settings.get("download_mode") or settings.DOWNLOAD_MODE)
    except Exception as e:
        logger.warning(f"Failed to read runtime download mode: {e}")
        return str(settings.DOWNLOAD_MODE)


async def _fetch_gallery_metadata(url: str) -> tuple[int, str, dict, bool]:
    from app.core.client import eh_client

    match = re.search(r"/g/(\d+)/(\w+)/?", url)
    if not match:
        raise ValueError("无效的链接格式")

    gid = int(match.group(1))
    token = match.group(2)
    domain = "exhentai.org" if "exhentai.org" in url else "e-hentai.org"

    actual_gid = gid
    actual_token = token
    has_newer_version = False
    max_depth = 10
    current_url = f"https://{domain}/g/{gid}/{token}/"

    metadata = {
        "title": f"Gallery {gid}",
        "title_jpn": None,
        "category": "Manual",
        "uploader": None,
        "filecount": 0,
        "posted": datetime.utcnow(),
        "tags": None,
    }

    try:
        depth = 0
        while depth < max_depth:
            html = await eh_client.get_html(current_url)
            if not html:
                break

            info = EHParser.parse_gallery_detail(html)
            if info.get("title"):
                metadata["title"] = info["title"]
            elif info.get("title_jpn"):
                metadata["title"] = info["title_jpn"]

            metadata["title_jpn"] = info.get("title_jpn") or metadata["title_jpn"]
            metadata["category"] = info.get("category") or metadata["category"]
            metadata["uploader"] = info.get("uploader") or metadata["uploader"]
            metadata["filecount"] = info.get("filecount") or metadata["filecount"]
            metadata["posted"] = info.get("posted") or metadata["posted"]
            metadata["tags"] = info.get("tags") or metadata["tags"]

            if info.get("is_outdated") and info.get("replaced_by"):
                newer_url = str(info["replaced_by"])
                logger.info(f"Gallery {actual_gid} has newer version: {newer_url}")
                newer_match = re.search(r"/g/(\d+)/(\w+)/?", newer_url)
                if newer_match:
                    actual_gid = int(newer_match.group(1))
                    actual_token = newer_match.group(2)
                    current_url = newer_url
                    has_newer_version = True
                    depth += 1
                    continue
            break
    except Exception as e:
        logger.warning(f"Could not fetch gallery info for {gid}: {e}")

    return actual_gid, actual_token, metadata, has_newer_version


def _apply_metadata(gallery: Gallery, metadata: dict, *, original_gid: int, has_newer_version: bool, download_mode: str) -> None:
    gallery.title = metadata.get("title") or gallery.title or f"Gallery {gallery.gid}"
    gallery.title_jpn = metadata.get("title_jpn") or gallery.title_jpn
    gallery.category = metadata.get("category") or gallery.category or "Manual"
    gallery.uploader = metadata.get("uploader") or gallery.uploader
    gallery.filecount = int(metadata.get("filecount") or gallery.filecount or 0)
    gallery.posted = metadata.get("posted") or gallery.posted or datetime.utcnow()
    gallery.tags = metadata.get("tags") or gallery.tags
    gallery.download_mode = download_mode
    gallery.parent_gid = str(original_gid) if has_newer_version else None


async def queue_manual_gallery(url: str, db: AsyncSession) -> ManualQueueResult:
    url = url.strip()
    if not url:
        raise ValueError("链接不能为空")

    original_match = re.search(r"/g/(\d+)/(\w+)/?", url)
    if not original_match:
        raise ValueError("无效的链接格式")

    original_gid = int(original_match.group(1))
    runtime_download_mode = await _get_runtime_download_mode()
    actual_gid, actual_token, metadata, has_newer_version = await _fetch_gallery_metadata(url)

    stmt = select(Gallery).where(Gallery.gid == actual_gid)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    title = str(metadata.get("title") or f"Gallery {actual_gid}")

    if existing:
        existing.token = actual_token
        _apply_metadata(
            existing,
            metadata,
            original_gid=original_gid,
            has_newer_version=has_newer_version,
            download_mode=runtime_download_mode,
        )

        if existing.status in [DownloadStatus.COMPLETED, DownloadStatus.ARCHIVED]:
            await db.commit()
            if has_newer_version:
                return ManualQueueResult(
                    status="Exists",
                    message=f"新版本画廊已存在且已完成: {title[:50]} (gid={actual_gid})",
                    gid=actual_gid,
                    token=actual_token,
                    title=title,
                    has_newer_version=True,
                )
            return ManualQueueResult(
                status="Exists",
                message=f"画廊已存在且已完成: {title[:50]}",
                gid=actual_gid,
                token=actual_token,
                title=title,
            )

        existing.status = DownloadStatus.PENDING
        existing.priority = 10
        existing.error_msg = None
        existing.requested_quality = None
        existing.resolved_quality = None
        await db.commit()
        if has_newer_version:
            return ManualQueueResult(
                status="Queued",
                message=f"检测到新版本，已重置并加入下载队列: {title[:50]} (gid={actual_gid})",
                gid=actual_gid,
                token=actual_token,
                title=title,
                has_newer_version=True,
            )
        return ManualQueueResult(
            status="Queued",
            message=f"已重置并加入下载队列: {title[:50]}",
            gid=actual_gid,
            token=actual_token,
            title=title,
        )

    new_gallery = Gallery(
        gid=actual_gid,
        token=actual_token,
        title=title,
        title_jpn=metadata.get("title_jpn"),
        category=metadata.get("category") or "Manual",
        uploader=metadata.get("uploader"),
        posted=metadata.get("posted") or datetime.utcnow(),
        filecount=int(metadata.get("filecount") or 0),
        tags=metadata.get("tags"),
        status=DownloadStatus.PENDING,
        priority=10,
        download_mode=runtime_download_mode,
        parent_gid=str(original_gid) if has_newer_version else None,
    )
    db.add(new_gallery)
    await db.commit()

    if has_newer_version:
        return ManualQueueResult(
            status="Added",
            message=f"检测到新版本，已加入下载队列: {title[:50]} (gid={actual_gid})",
            gid=actual_gid,
            token=actual_token,
            title=title,
            has_newer_version=True,
        )
    return ManualQueueResult(
        status="Added",
        message=f"已加入下载队列: {title[:50]}",
        gid=actual_gid,
        token=actual_token,
        title=title,
    )
