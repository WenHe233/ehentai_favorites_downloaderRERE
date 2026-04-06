"""
Native Python crawler for E-Hentai/ExHentai galleries.
Supports cancellation, cleanup, concurrent image downloads, and resumable partial downloads.
"""
import asyncio
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from inspect import isawaitable
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import aiofiles
import httpx
from bs4 import BeautifulSoup
from loguru import logger

from app.core.client import eh_client
from app.core.config import settings
from app.core.output_template import (
    OutputTemplateSettings,
    build_output_context,
    resolve_output_targets,
)
from app.core.parser import EHParser


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ImageDownloadResult:
    file_path: Optional[Path]
    error: Optional[str] = None
    image_url: Optional[str] = None
    quality: Optional[str] = None


@dataclass
class GalleryDownloadResult:
    success: bool
    file_path: Optional[str]
    error: Optional[str] = None
    quality: Optional[str] = None
    completed_at: Optional[datetime] = None


class NativeCrawler:
    """
    Native crawler that downloads gallery images with concurrency support.
    Supports cancellation via callback function and resumable partial downloads.
    """

    @staticmethod
    async def _notify_progress(
        progress_callback: Optional[Callable[..., Awaitable[None] | None]],
        **payload,
    ) -> None:
        if not progress_callback:
            return

        result = progress_callback(**payload)
        if isawaitable(result):
            await result

    @staticmethod
    async def _build_request_context() -> Tuple[Dict[str, str], Optional[str], str]:
        from app.services.config_service import config_service

        db_settings = await config_service.get_all_settings()
        cookies: Dict[str, str] = {}
        if db_settings.get("ipb_member_id"):
            cookies["ipb_member_id"] = db_settings["ipb_member_id"]
        if db_settings.get("ipb_pass_hash"):
            cookies["ipb_pass_hash"] = db_settings["ipb_pass_hash"]
        if db_settings.get("igneous"):
            cookies["igneous"] = db_settings["igneous"]

        proxy_url = db_settings.get("proxy_url") or settings.PROXY_URL
        return cookies, proxy_url, settings.USER_AGENT

    @staticmethod
    def _get_resume_root() -> Path:
        root = settings.DATA_DIR / "native_resume"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _get_temp_dir(gid: str) -> Path:
        return NativeCrawler._get_resume_root() / gid

    @staticmethod
    def _get_manifest_path(temp_dir: Path) -> Path:
        return temp_dir / "resume_manifest.json"

    @staticmethod
    def _scan_downloaded_files(temp_dir: Path, total_pages: int) -> Dict[int, Path]:
        downloaded_files: Dict[int, Path] = {}
        if not temp_dir.exists():
            return downloaded_files

        for path in temp_dir.iterdir():
            if not path.is_file():
                continue
            match = re.match(r"^(\d{4})\.", path.name)
            if not match:
                continue
            index = int(match.group(1))
            if 1 <= index <= total_pages:
                downloaded_files[index] = path
        return downloaded_files

    @staticmethod
    def _load_resume_manifest(temp_dir: Path) -> Optional[Dict]:
        manifest_path = NativeCrawler._get_manifest_path(temp_dir)
        if not manifest_path.exists():
            return None

        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load resume manifest {manifest_path}: {e}")
            return None

    @staticmethod
    def _write_resume_manifest(temp_dir: Path, payload: Dict) -> None:
        temp_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = NativeCrawler._get_manifest_path(temp_dir)
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _remove_file(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            logger.warning(f"Failed to remove file {path}: {e}")

    @staticmethod
    def _format_missing_pages(missing_pages: List[int]) -> str:
        if not missing_pages:
            return "无"
        preview = ", ".join(str(page) for page in missing_pages[:6])
        if len(missing_pages) > 6:
            preview += f" ... 共 {len(missing_pages)} 页"
        return preview

    @staticmethod
    def _format_failed_pages(failed_pages: Dict[int, str]) -> str:
        details = [f"第 {idx} 页: {message}" for idx, message in sorted(failed_pages.items())]
        summary = "；".join(details[:3])
        if len(details) > 3:
            summary += f"；另有 {len(details) - 3} 页失败"
        return summary

    @staticmethod
    def get_resume_metadata(gid: int, output_dir: Optional[str] = None) -> Optional[Dict]:
        temp_dir = NativeCrawler._get_temp_dir(str(gid))
        manifest = NativeCrawler._load_resume_manifest(temp_dir)
        if not manifest:
            return None

        total_pages = int(manifest.get("total_pages") or 0)
        completed_pages = int(manifest.get("completed_pages") or 0)
        missing_pages = [int(page) for page in manifest.get("missing_pages") or []]
        return {
            "gid": gid,
            "title": manifest.get("title"),
            "safe_title": manifest.get("safe_title"),
            "total_pages": total_pages,
            "completed_pages": completed_pages,
            "missing_pages": missing_pages,
            "page_errors": manifest.get("page_errors") or {},
            "partial_zip_path": manifest.get("partial_zip_path"),
            "updated_at": manifest.get("updated_at") or _utcnow_iso(),
        }

    @staticmethod
    def build_partial_progress(gid: int, error_msg: Optional[str] = None, output_dir: Optional[str] = None) -> Optional[Dict]:
        metadata = NativeCrawler.get_resume_metadata(gid, output_dir=output_dir)
        if not metadata:
            return None

        total_pages = metadata.get("total_pages") or 0
        completed_pages = metadata.get("completed_pages") or 0
        percent = round((completed_pages / total_pages) * 100, 2) if total_pages else 0.0
        missing_pages = metadata.get("missing_pages") or []
        detail = (
            f"已完成 {completed_pages}/{total_pages} 张图片，待补抓页: "
            f"{NativeCrawler._format_missing_pages(missing_pages)}"
        )
        if error_msg:
            detail = f"{detail}；{error_msg}"

        return {
            "phase": "partial",
            "percent": percent,
            "current": completed_pages,
            "total": total_pages,
            "unit": "images",
            "detail": detail,
            "updated_at": metadata.get("updated_at") or _utcnow_iso(),
        }

    @staticmethod
    def cleanup_resume_artifacts(gid: int, output_dir: Optional[str] = None) -> int:
        temp_dir = NativeCrawler._get_temp_dir(str(gid))
        manifest = NativeCrawler._load_resume_manifest(temp_dir)
        deleted = 0
        partial_candidates: set[Path] = set()

        if manifest and manifest.get("partial_zip_path"):
            partial_candidates.add(Path(manifest["partial_zip_path"]))

        legacy_output_path = Path(output_dir) if output_dir else settings.DOWNLOAD_DIR
        if legacy_output_path.exists():
            prefix = f"[{gid}] "
            for path in legacy_output_path.iterdir():
                if path.is_file() and path.name.startswith(prefix) and path.name.endswith(".partial.zip"):
                    partial_candidates.add(path)

        for path in partial_candidates:
            if path.exists():
                NativeCrawler._remove_file(path)
                deleted += 1

        if temp_dir.exists():
            try:
                import shutil

                shutil.rmtree(temp_dir)
                deleted += 1
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir {temp_dir}: {e}")

        return deleted

    @staticmethod
    def describe_resume_artifacts(gid: int) -> Dict[str, Any]:
        temp_dir = NativeCrawler._get_temp_dir(str(gid))
        manifest = NativeCrawler._load_resume_manifest(temp_dir)
        downloaded_files = 0

        if temp_dir.exists():
            for path in temp_dir.iterdir():
                if not path.is_file():
                    continue
                if path.name == "resume_manifest.json":
                    continue
                if re.match(r"^(\d{4})\.", path.name):
                    downloaded_files += 1

        partial_zip_path = manifest.get("partial_zip_path") if manifest else None
        partial_zip_exists = bool(partial_zip_path and Path(str(partial_zip_path)).exists())

        return {
            "has_artifacts": downloaded_files > 0 or partial_zip_exists or bool(manifest),
            "downloaded_files": downloaded_files,
            "manifest_exists": manifest is not None,
            "partial_zip_exists": partial_zip_exists,
            "partial_zip_path": str(partial_zip_path) if partial_zip_path else None,
        }

    @staticmethod
    async def _write_zip(
        zip_path: Path,
        downloaded_files: Dict[int, Path],
        progress_callback: Optional[Callable[..., Awaitable[None] | None]],
        *,
        detail_prefix: str,
        percent_start: float,
        percent_span: float,
    ) -> None:
        NativeCrawler._remove_file(zip_path)
        sorted_keys = sorted(downloaded_files.keys())
        total_files = len(sorted_keys)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for position, idx in enumerate(sorted_keys, 1):
                file_path = downloaded_files[idx]
                archive.write(file_path, file_path.name)
                percent = percent_start + ((position / total_files) * percent_span)
                await NativeCrawler._notify_progress(
                    progress_callback,
                    phase="packaging",
                    percent=percent,
                    current=position,
                    total=total_files,
                    unit="files",
                    detail=f"{detail_prefix} {position}/{total_files} 个文件",
                )

    @staticmethod
    async def download(
        url: str,
        output_dir: Optional[str] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        prefer_jpn_title: bool = True,
        max_concurrent_images: int = 3,
        max_retries: int = 3,
        progress_callback: Optional[Callable[..., Awaitable[None] | None]] = None,
        preferred_quality: str = "native",
        output_template_settings: Optional[OutputTemplateSettings] = None,
        output_context: Optional[Mapping[str, Any]] = None,
    ) -> GalleryDownloadResult:
        """
        Download a gallery using native HTTP requests with concurrent image downloads.
        """
        match = re.search(r"/g/(\d+)/(\w+)/?", url)
        if not match:
            logger.error(f"Invalid gallery URL: {url}")
            return GalleryDownloadResult(False, None, "无效的画廊链接")

        overall_quality = preferred_quality

        gid = match.group(1)
        logger.info(f"[NativeCrawler] Starting download for {url} (concurrent: {max_concurrent_images})")

        try:
            html = await eh_client.get_html(url)
            if not html:
                logger.error(f"Failed to fetch gallery page: {url}")
                return GalleryDownloadResult(False, None, "获取画廊首页失败")

            soup = BeautifulSoup(html, "lxml")
            detail = EHParser.parse_gallery_detail(html)
            resolved_output_context = build_output_context(
                gid=gid,
                title=(output_context or {}).get("title") or detail.get("title") or f"Gallery_{gid}",
                jpn_title=(output_context or {}).get("jpn_title") or detail.get("title_jpn"),
                category=(output_context or {}).get("category") or detail.get("category"),
                uploader=(output_context or {}).get("uploader") or detail.get("uploader"),
                filecount=(output_context or {}).get("filecount") or detail.get("filecount"),
                quality=preferred_quality,
                parent_gid=(output_context or {}).get("parent_gid"),
                downloaded_at=(output_context or {}).get("downloaded_at"),
                favorited_at=(output_context or {}).get("favorited_at"),
                fav=(output_context or {}).get("fav"),
            )

            temp_dir = NativeCrawler._get_temp_dir(gid)
            resume_manifest = NativeCrawler._load_resume_manifest(temp_dir)
            overall_quality = str(resume_manifest.get("quality")) if resume_manifest and resume_manifest.get("quality") else preferred_quality
            if resume_manifest and resume_manifest.get("title") and not resolved_output_context.get("title"):
                resolved_output_context["title"] = str(resume_manifest["title"])

            if is_cancelled and is_cancelled():
                logger.info(f"[NativeCrawler] Download cancelled for {gid}")
                return GalleryDownloadResult(False, None, "下载已取消")

            page_urls = await NativeCrawler._get_page_urls(url, soup)
            if not page_urls:
                logger.error(f"No pages found for gallery {gid}")
                return GalleryDownloadResult(False, None, "未解析到图片页面")

            total_pages = len(page_urls)
            downloaded_files = NativeCrawler._scan_downloaded_files(temp_dir, total_pages)
            if output_template_settings and output_template_settings.conflict_strategy == "overwrite" and not downloaded_files:
                NativeCrawler.cleanup_resume_artifacts(int(gid))
                temp_dir = NativeCrawler._get_temp_dir(gid)
                resume_manifest = None
                downloaded_files = {}

            if downloaded_files:
                logger.info(
                    f"[NativeCrawler] Resuming gallery {gid}: "
                    f"{len(downloaded_files)}/{total_pages} images already present"
                )
                await NativeCrawler._notify_progress(
                    progress_callback,
                    phase="preparing",
                    percent=10,
                    current=len(downloaded_files),
                    total=total_pages,
                    unit="images",
                    detail=f"检测到断点数据，已保留 {len(downloaded_files)}/{total_pages} 张图片",
                )
            else:
                logger.info(f"[NativeCrawler] Found {total_pages} pages for {gid}")
                await NativeCrawler._notify_progress(
                    progress_callback,
                    phase="preparing",
                    percent=10,
                    current=0,
                    total=total_pages,
                    unit="images",
                    detail=f"已解析 {total_pages} 张图片",
                )

            temp_dir.mkdir(parents=True, exist_ok=True)

            try:
                missing_indices = [idx for idx in range(1, total_pages + 1) if idx not in downloaded_files]
                failed_pages: Dict[int, str] = {}
                progress_lock = asyncio.Lock()

                async def download_with_sem(idx: int, page_url: str, semaphore: asyncio.Semaphore) -> None:
                    nonlocal overall_quality
                    if is_cancelled and is_cancelled():
                        return

                    async with semaphore:
                        if is_cancelled and is_cancelled():
                            return

                        logger.debug(f"[NativeCrawler] Downloading page {idx}/{total_pages}")
                        result = await NativeCrawler._download_page_image(
                            page_url,
                            temp_dir,
                            idx,
                            max_retries=max_retries,
                            preferred_quality=preferred_quality,
                        )
                        if result.file_path:
                            async with progress_lock:
                                downloaded_files[idx] = result.file_path
                                completed = len(downloaded_files)
                                if (result.quality or preferred_quality) == "native":
                                    overall_quality = "native"
                            percent = 10 + ((completed / total_pages) * 80)
                            await NativeCrawler._notify_progress(
                                progress_callback,
                                phase="downloading",
                                percent=percent,
                                current=completed,
                                total=total_pages,
                                unit="images",
                                detail=f"已下载 {completed}/{total_pages} 张图片",
                            )
                        else:
                            failed_pages[idx] = result.error or "下载失败"
                            logger.warning(f"Failed to download page {idx}: {failed_pages[idx]}")

                if missing_indices:
                    semaphore = asyncio.Semaphore(max_concurrent_images)
                    tasks = [
                        download_with_sem(idx, page_urls[idx - 1], semaphore)
                        for idx in missing_indices
                    ]
                    await asyncio.gather(*tasks)

                if is_cancelled and is_cancelled():
                    logger.info(f"[NativeCrawler] Download cancelled during image fetch for {gid}")
                    return GalleryDownloadResult(False, None, "下载已取消", quality=overall_quality)

                if failed_pages:
                    logger.warning(
                        f"[NativeCrawler] {len(failed_pages)} images failed in concurrent pass, retrying sequentially"
                    )
                    for idx in sorted(list(failed_pages.keys())):
                        if is_cancelled and is_cancelled():
                            logger.info(f"[NativeCrawler] Download cancelled during retry pass for {gid}")
                            return GalleryDownloadResult(False, None, "下载已取消", quality=overall_quality)

                        await NativeCrawler._notify_progress(
                            progress_callback,
                            phase="downloading",
                            percent=10 + ((len(downloaded_files) / total_pages) * 80),
                            current=len(downloaded_files),
                            total=total_pages,
                            unit="images",
                            detail=f"正在补抓失败页 {idx}/{total_pages}",
                        )
                        result = await NativeCrawler._download_page_image(
                            page_urls[idx - 1],
                            temp_dir,
                            idx,
                            max_retries=max(max_retries + 2, 5),
                            preferred_quality=preferred_quality,
                        )
                        if result.file_path:
                            downloaded_files[idx] = result.file_path
                            failed_pages.pop(idx, None)
                            completed = len(downloaded_files)
                            if (result.quality or preferred_quality) == "native":
                                overall_quality = "native"
                            percent = 10 + ((completed / total_pages) * 80)
                            await NativeCrawler._notify_progress(
                                progress_callback,
                                phase="downloading",
                                percent=percent,
                                current=completed,
                                total=total_pages,
                                unit="images",
                                detail=f"补抓成功，已下载 {completed}/{total_pages} 张图片",
                            )
                        else:
                            failed_pages[idx] = result.error or failed_pages[idx]

                if not downloaded_files:
                    logger.error(f"No images downloaded for {gid}")
                    NativeCrawler.cleanup_resume_artifacts(int(gid))
                    return GalleryDownloadResult(False, None, "所有图片下载失败")

                # Re-scan files from disk before packaging so transient candidate
                # failures or cleanup races do not leave stale in-memory paths.
                downloaded_files = NativeCrawler._scan_downloaded_files(temp_dir, total_pages)
                missing_after_scan = [
                    idx for idx in range(1, total_pages + 1) if idx not in downloaded_files
                ]
                for idx in missing_after_scan:
                    failed_pages.setdefault(idx, "下载文件缺失，已跳过")

                if not downloaded_files:
                    logger.error(f"No image files remain on disk for {gid}")
                    NativeCrawler.cleanup_resume_artifacts(int(gid))
                    return GalleryDownloadResult(False, None, "下载文件缺失，无法打包", quality=overall_quality)

                completed_at = datetime.now(timezone.utc)
                resolved_output_context["quality"] = overall_quality
                resolved_output_context["downloaded_at"] = completed_at
                active_template_settings = output_template_settings or OutputTemplateSettings(
                    template=settings.OUTPUT_TEMPLATE,
                    conflict_strategy=settings.CONFLICT_STRATEGY,
                    truncate_enabled=settings.TRUNCATE_FILENAMES,
                    max_length=settings.FILENAME_MAX_LENGTH,
                    timezone_mode=settings.FAV_DATE_TIMEZONE,
                    base_dir=settings.BASE_DIR,
                )
                final_zip_path, partial_zip_path = resolve_output_targets(
                    settings=active_template_settings,
                    context=resolved_output_context,
                )

                if resume_manifest and resume_manifest.get("partial_zip_path"):
                    previous_partial = Path(str(resume_manifest["partial_zip_path"]))
                    if previous_partial != partial_zip_path:
                        NativeCrawler._remove_file(previous_partial)

                if failed_pages:
                    error_detail = NativeCrawler._format_failed_pages(failed_pages)
                    if active_template_settings.conflict_strategy == "overwrite":
                        NativeCrawler._remove_file(partial_zip_path)
                        NativeCrawler._remove_file(final_zip_path)
                    await NativeCrawler._write_zip(
                        partial_zip_path,
                        downloaded_files,
                        progress_callback,
                        detail_prefix="正在打包部分归档",
                        percent_start=90,
                        percent_span=8,
                    )
                    manifest_payload = {
                        "gid": gid,
                        "title": resolved_output_context.get("title"),
                        "total_pages": total_pages,
                        "completed_pages": len(downloaded_files),
                        "missing_pages": sorted(failed_pages.keys()),
                        "page_errors": failed_pages,
                        "partial_zip_path": str(partial_zip_path),
                        "quality": overall_quality,
                        "updated_at": _utcnow_iso(),
                    }
                    NativeCrawler._write_resume_manifest(temp_dir, manifest_payload)
                    logger.info(
                        f"[NativeCrawler] Created partial archive for {gid}: {partial_zip_path} "
                        f"({len(downloaded_files)}/{total_pages})"
                    )
                    logger.warning(f"[NativeCrawler] Remaining failed pages: {error_detail}")
                    return GalleryDownloadResult(
                        False,
                        str(partial_zip_path),
                        error_detail,
                        quality=overall_quality,
                    )

                if active_template_settings.conflict_strategy == "overwrite":
                    NativeCrawler._remove_file(final_zip_path)
                    NativeCrawler._remove_file(partial_zip_path)
                await NativeCrawler._write_zip(
                    final_zip_path,
                    downloaded_files,
                    progress_callback,
                    detail_prefix="正在打包",
                    percent_start=90,
                    percent_span=10,
                )

                NativeCrawler.cleanup_resume_artifacts(int(gid))
                logger.info(f"[NativeCrawler] Successfully downloaded {gid} -> {final_zip_path}")
                return GalleryDownloadResult(
                    True,
                    str(final_zip_path),
                    None,
                    quality=overall_quality,
                    completed_at=completed_at,
                )
            except Exception as e:
                logger.error(f"[NativeCrawler] Error during download: {e}")
                raise
        except asyncio.CancelledError:
            logger.info(f"[NativeCrawler] Download task cancelled for {gid}")
            return GalleryDownloadResult(False, None, "下载已取消", quality=overall_quality)
        except Exception as e:
            logger.error(f"[NativeCrawler] Error downloading {url}: {e}")
            return GalleryDownloadResult(False, None, str(e), quality=overall_quality)

    @staticmethod
    async def _get_page_urls(gallery_url: str, first_page_soup: BeautifulSoup) -> List[str]:
        """Get all image page URLs from gallery."""
        page_urls: List[str] = []

        for a in first_page_soup.select("#gdt a"):
            href = a.get("href", "")
            if "/s/" in href:
                page_urls.append(href)

        next_pages: List[str] = []
        for a in first_page_soup.select(".ptt a"):
            href = a.get("href", "")
            if href and "?p=" in href and href not in next_pages:
                next_pages.append(href)

        for page_url in next_pages[:-1]:
            try:
                html = await eh_client.get_html(page_url)
                if html:
                    soup = BeautifulSoup(html, "lxml")
                    for a in soup.select("#gdt a"):
                        href = a.get("href", "")
                        if "/s/" in href and href not in page_urls:
                            page_urls.append(href)
            except Exception as e:
                logger.warning(f"Failed to fetch gallery page: {e}")

        return page_urls

    @staticmethod
    async def _download_page_image(
        page_url: str,
        temp_dir: Path,
        index: int,
        max_retries: int = 3,
        preferred_quality: str = "native",
    ) -> ImageDownloadResult:
        """Download image from a single page with retry support."""
        temp_dir.mkdir(parents=True, exist_ok=True)
        last_error = None
        last_image_url = None

        for attempt in range(max_retries):
            file_path: Optional[Path] = None
            try:
                if attempt > 0:
                    logger.info(f"[NativeCrawler] Retry {attempt}/{max_retries} for page {index}")
                    await asyncio.sleep(2 * attempt)

                html = await eh_client.get_html(page_url)
                if not html:
                    last_error = "Empty HTML response"
                    continue

                soup = BeautifulSoup(html, "lxml")
                img = soup.select_one("#img") or soup.select_one("#i3 img")
                if not img:
                    last_error = "No image tag found"
                    continue

                native_url = img.get("src", "")
                if not native_url:
                    last_error = "Empty image URL"
                    continue

                original_url = ""
                for link in soup.select("#i6 a[href]"):
                    href = link.get("href", "").strip()
                    text = link.get_text(" ", strip=True).lower()
                    if "/fullimg/" in href or "download original" in text:
                        original_url = href
                        break

                candidate_urls: list[tuple[str, str]] = []
                if preferred_quality == "original" and original_url:
                    candidate_urls.append((original_url, "original"))
                candidate_urls.append((native_url, "native"))

                seen_urls: set[str] = set()
                for img_url, resolved_quality in candidate_urls:
                    if not img_url or img_url in seen_urls:
                        continue
                    seen_urls.add(img_url)
                    last_image_url = img_url

                    ext_match = re.search(r"\.(jpg|jpeg|png|gif|webp)", img_url, re.I)
                    ext = ext_match.group(1).lower() if ext_match else "jpg"
                    file_path = temp_dir / f"{index:04d}.{ext}"
                    NativeCrawler._remove_file(file_path)

                    cookies, proxy_url, user_agent = await NativeCrawler._build_request_context()
                    try:
                        async with httpx.AsyncClient(
                            cookies=cookies,
                            proxy=proxy_url,
                            timeout=httpx.Timeout(connect=30.0, read=120.0, write=60.0, pool=30.0),
                            follow_redirects=True,
                            headers={
                                "User-Agent": user_agent,
                                "Referer": page_url,
                                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                            },
                        ) as client:
                            async with client.stream("GET", img_url) as response:
                                response.raise_for_status()

                                content_type = response.headers.get("content-type", "")
                                if "text/html" in content_type.lower():
                                    last_error = f"Unexpected content-type: {content_type}"
                                    continue

                                bytes_written = 0
                                async with aiofiles.open(file_path, "wb") as f:
                                    async for chunk in response.aiter_bytes():
                                        if not chunk:
                                            continue
                                        await f.write(chunk)
                                        bytes_written += len(chunk)

                            expected_length = response.headers.get("content-length")
                            if expected_length and bytes_written != int(expected_length):
                                last_error = (
                                    f"received {bytes_written} bytes, expected {expected_length}"
                                )
                                NativeCrawler._remove_file(file_path)
                                continue

                            if bytes_written < 1000:
                                last_error = f"Content too small ({bytes_written} bytes)"
                                NativeCrawler._remove_file(file_path)
                                continue
                    except Exception as candidate_error:
                        last_error = str(candidate_error).strip() or candidate_error.__class__.__name__ or "下载失败"
                        logger.debug(
                            f"[NativeCrawler] Candidate {resolved_quality} failed for page {index}: {last_error}"
                        )
                        if file_path:
                            NativeCrawler._remove_file(file_path)
                        continue

                    return ImageDownloadResult(file_path=file_path, image_url=img_url, quality=resolved_quality)
            except Exception as e:
                last_error = str(e).strip() or e.__class__.__name__ or "下载失败"
                logger.debug(f"[NativeCrawler] Attempt {attempt + 1} failed for page {index}: {last_error}")
                if file_path:
                    NativeCrawler._remove_file(file_path)

        logger.error(f"Failed to download image from {page_url} after {max_retries} attempts: {last_error}")
        return ImageDownloadResult(
            file_path=None,
            error=last_error or "下载失败",
            image_url=last_image_url,
            quality="native" if preferred_quality == "original" else preferred_quality,
        )
