import asyncio
from dataclasses import dataclass
import re
import aiofiles
from loguru import logger
from inspect import isawaitable
from typing import Awaitable, Callable, Optional, Tuple, Dict
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
import httpx
from app.core.config import settings


@dataclass
class ArchiveDownloadResult:
    success: bool
    error_msg: Optional[str] = None
    should_refresh_url: bool = False


class GalleryArchiver:
    """
    Downloads galleries using E-Hentai's archiver feature (GP-based).
    Based on reference implementation with polling logic.
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
    def _build_archiver_url(domain: str, gid: int, token: str) -> str:
        """Build the archiver landing page URL (no archiver key needed)."""
        return f"https://{domain}/archiver.php?gid={gid}&token={token}"
    
    @staticmethod
    async def _get_cookies() -> Dict[str, str]:
        """Get cookies from dynamic settings."""
        try:
            from app.services.config_service import config_service
            db_settings = await config_service.get_all_settings()
            cookies = {}
            if db_settings.get("ipb_member_id"):
                cookies["ipb_member_id"] = db_settings["ipb_member_id"]
            if db_settings.get("ipb_pass_hash"):
                cookies["ipb_pass_hash"] = db_settings["ipb_pass_hash"]
            if db_settings.get("igneous"):
                cookies["igneous"] = db_settings["igneous"]
            return cookies
        except Exception as e:
            logger.warning(f"Could not get cookies: {e}")
            return {}
    
    @staticmethod
    async def _get_domain() -> str:
        """Get domain from settings."""
        try:
            from app.services.config_service import config_service
            db_settings = await config_service.get_all_settings()
            return db_settings.get("eh_domain") or settings.EH_DOMAIN
        except Exception:
            return settings.EH_DOMAIN

    @staticmethod
    def _ensure_start_param(url: str) -> str:
        """
        Ensure hath.network archive URLs have start=1 parameter.
        Without this, you get HTML page instead of actual zip download.
        """
        if not url:
            return url
        pu = urlparse(url)
        if pu.netloc.endswith("hath.network") and "/archive/" in pu.path:
            qs = parse_qs(pu.query)
            if "start" not in qs:
                qs["start"] = ["1"]
                new_query = urlencode(qs, doseq=True)
                url = urlunparse((pu.scheme, pu.netloc, pu.path, pu.params, new_query, pu.fragment))
                logger.info(f"Added start=1 to URL: {url}")
        return url

    @staticmethod
    async def prepare_and_poll(
        gid: int, 
        token: str, 
        quality: str = None, 
        poll_interval_sec: int = 3, 
        max_wait_sec: int = 120,
        is_cancelled: Optional[callable] = None,
        progress_callback: Optional[Callable[..., Awaitable[None] | None]] = None,
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Navigate the archiver page and get the download URL.
        
        Returns: (download_url, estimated_size_bytes) or (None, None) on failure
        """
        quality = quality or settings.ARCHIVE_QUALITY
        domain = await GalleryArchiver._get_domain()
        url = GalleryArchiver._build_archiver_url(domain, gid, token)
        cookies = await GalleryArchiver._get_cookies()
        
        logger.info(f"Starting archiver process for gid={gid}")
        
        started = asyncio.get_event_loop().time()
        posted = False

        await GalleryArchiver._notify_progress(
            progress_callback,
            phase="preparing",
            percent=10,
            current=0,
            total=max_wait_sec,
            unit="steps",
            detail="准备归档下载",
        )
        
        async with httpx.AsyncClient(
            cookies=cookies, 
            proxy=settings.PROXY_URL,
            timeout=30.0, 
            follow_redirects=True
        ) as client:
            while True:
                # Check cancellation
                if is_cancelled and is_cancelled():
                    logger.info(f"Archiver cancelled for gid={gid}")
                    return None, None
                
                try:
                    elapsed = asyncio.get_event_loop().time() - started
                    if elapsed > max_wait_sec:
                        logger.error(f"Archiver timeout for gid={gid}")
                        return None, None

                    poll_percent = 10 + min(15, (elapsed / max_wait_sec) * 15)
                    await GalleryArchiver._notify_progress(
                        progress_callback,
                        phase="polling",
                        percent=poll_percent,
                        current=round(elapsed, 1),
                        total=max_wait_sec,
                        unit="steps",
                        detail="等待归档链接就绪",
                    )
                    
                    logger.debug(f"Fetching archiver page: {url}")
                    r = await client.get(url)
                    
                    if r.status_code != 200:
                        logger.warning(f"Archiver status {r.status_code}")
                        await asyncio.sleep(poll_interval_sec)
                        continue
                    
                    soup = BeautifulSoup(r.text, "lxml")
                    
                    # Check for direct download link (.zip or containing 'download')
                    for a in soup.select("a"):
                        href = a.get("href", "")
                        if href.endswith(".zip") or "download" in href.lower():
                            size = GalleryArchiver._parse_size(soup.get_text(" "))
                            href = GalleryArchiver._ensure_start_param(href)
                            logger.info(f"Archiver download ready: {href}")
                            return href, size
                    
                    # Check for JS redirect
                    js_text = soup.get_text(" ")
                    mredir = re.search(r'(?:document|window)?\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', js_text, re.I)
                    if mredir:
                        ah = mredir.group(1)
                        if ah.startswith("/"):
                            pu = urlparse(url)
                            ah = f"{pu.scheme}://{pu.netloc}{ah}"
                        if "start=" in ah or ah.endswith(".zip"):
                            size = GalleryArchiver._parse_size(js_text)
                            ah = GalleryArchiver._ensure_start_param(ah)
                            logger.info(f"Archiver download ready (js): {ah}")
                            return ah, size
                        logger.info(f"Archiver redirect to: {ah}")
                        url = ah
                        await asyncio.sleep(poll_interval_sec)
                        continue
                    
                    # Check for start button
                    for a in soup.select("a"):
                        href = a.get("href", "")
                        if "start=" in href or ("/archive/" in href and "hath.network" in href):
                            if href.startswith("/"):
                                pu = urlparse(url)
                                start_url = f"{pu.scheme}://{pu.netloc}{href}"
                            else:
                                start_url = href
                            start_url = GalleryArchiver._ensure_start_param(start_url)
                            logger.info(f"Archiver start button found: {start_url}")
                            return start_url, None
                    
                    # If not posted yet, find and submit the form
                    if not posted:
                        for form in soup.select("form"):
                            action = form.get("action") or url
                            dltype = form.select_one("input[name='dltype']")
                            dlcheck_btn = form.select_one("input[name='dlcheck']")
                            
                            if dltype:
                                v = dltype.get("value", "")
                                want = "org" if quality == "original" else "res"
                                if v == want:
                                    dlcheck_val = dlcheck_btn.get("value") if dlcheck_btn else (
                                        "Download Original Archive" if want == "org" else "Download Resample Archive"
                                    )
                                    post_data = {"dltype": want, "dlcheck": dlcheck_val}
                                    
                                    logger.info(f"Posting archiver form: action={action}, data={post_data}")
                                    pr = await client.post(
                                        action, 
                                        data=post_data, 
                                        headers={"Referer": url, "Origin": f"https://{domain}"}
                                    )
                                    
                                    if pr.status_code == 200:
                                        posted = True
                                        psoup = BeautifulSoup(pr.text, "lxml")
                                        
                                        # Check for JS redirect in response
                                        for sc in psoup.select("script"):
                                            txt = sc.string or sc.get_text() or ""
                                            m = re.search(r'(?:document|window)?\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', txt, re.I)
                                            if m:
                                                ah = m.group(1)
                                                if ah.startswith("/"):
                                                    pu = urlparse(url)
                                                    ah = f"{pu.scheme}://{pu.netloc}{ah}"
                                                if "start=" in ah or ah.endswith(".zip") or ("/archive/" in ah and "hath.network" in ah):
                                                    size = GalleryArchiver._parse_size(psoup.get_text(" "))
                                                    ah = GalleryArchiver._ensure_start_param(ah)
                                                    logger.info(f"Archiver download ready (post): {ah}")
                                                    return ah, size
                                                url = ah
                                                break
                                        
                                        # Check for download link in response
                                        for a in psoup.select("a"):
                                            href = a.get("href", "")
                                            if href.endswith(".zip") or "download" in href.lower() or "start=" in href or "/archive/" in href:
                                                if href.startswith("/"):
                                                    pu = urlparse(url)
                                                    ah = f"{pu.scheme}://{pu.netloc}{href}"
                                                else:
                                                    ah = href
                                                ah = GalleryArchiver._ensure_start_param(ah)
                                                size = GalleryArchiver._parse_size(psoup.get_text(" "))
                                                logger.info(f"Archiver download ready (post link): {ah}")
                                                return ah, size
                                    break
                    
                    await asyncio.sleep(poll_interval_sec)
                    
                except Exception as e:
                    logger.error(f"Archiver error: {e}")
                    await asyncio.sleep(poll_interval_sec)
        
        return None, None
    
    @staticmethod
    def _parse_size(text: str) -> Optional[int]:
        """Parse file size from page text."""
        m = re.search(r"(estimated\s+size|size)\s*:\s*([0-9\.]+)\s*(kb|mb|gb|kib|mib|gib)", text, re.I)
        if not m:
            return None
        val = float(m.group(2))
        unit = m.group(3).lower()
        if unit in ("kb", "kib"):
            return int(val * 1024)
        if unit in ("mb", "mib"):
            return int(val * 1024 * 1024)
        if unit in ("gb", "gib"):
            return int(val * 1024 * 1024 * 1024)
        return None
    
    @staticmethod
    async def download_file(
        url: str,
        output_path: str,
        is_cancelled: Optional[callable] = None,
        max_retries: int = 3,
        progress_callback: Optional[Callable[..., Awaitable[None] | None]] = None,
    ) -> ArchiveDownloadResult:
        """Download a file from URL to the specified path with verification and retry."""
        last_error = None
        should_refresh_url = False
        
        for attempt in range(max_retries):
            try:
                # Initial cancellation check
                if is_cancelled and is_cancelled():
                    logger.info("Archive download cancelled before start")
                    return ArchiveDownloadResult(success=False, error_msg="归档下载已取消")
                
                if attempt > 0:
                    logger.info(f"Retry {attempt}/{max_retries} for archive download")
                    await asyncio.sleep(3 * attempt)  # Exponential backoff
                
                # Ensure start=1 is in URL for hath.network
                download_url = GalleryArchiver._ensure_start_param(url)
                
                logger.info(f"Downloading archive from: {download_url}")
                cookies = await GalleryArchiver._get_cookies()
                
                async with httpx.AsyncClient(
                    cookies=cookies,
                    proxy=settings.PROXY_URL,
                    timeout=600.0,  # 10 minutes for large files
                    follow_redirects=True
                ) as client:
                    async with client.stream("GET", download_url) as response:
                        try:
                            response.raise_for_status()
                        except httpx.HTTPStatusError as exc:
                            status_code = exc.response.status_code
                            should_refresh_url = status_code in {403, 404, 410}
                            if should_refresh_url:
                                last_error = f"归档下载链接可能已失效（HTTP {status_code}）"
                            else:
                                last_error = f"归档下载失败（HTTP {status_code}）"
                            logger.warning(last_error)
                            continue
                        
                        # Check content type - should be application/zip or similar
                        content_type = response.headers.get("content-type", "")
                        if "text/html" in content_type:
                            should_refresh_url = True
                            last_error = f"归档下载链接可能已失效，返回了 HTML 页面（Content-Type: {content_type}）"
                            logger.warning(last_error)
                            continue

                        content_length = response.headers.get("content-length")
                        total_bytes = int(content_length) if content_length and content_length.isdigit() else None
                        downloaded_bytes = 0

                        await GalleryArchiver._notify_progress(
                            progress_callback,
                            phase="downloading",
                            percent=25 if total_bytes else 55,
                            current=0,
                            total=total_bytes,
                            unit="bytes",
                            detail="开始下载归档文件",
                        )
                        
                        async with aiofiles.open(output_path, 'wb') as f:
                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                # Check cancellation during download
                                if is_cancelled and is_cancelled():
                                    logger.info("Archive download cancelled during transfer")
                                    return False
                                downloaded_bytes += len(chunk)
                                await f.write(chunk)
                                if total_bytes:
                                    percent = 25 + ((downloaded_bytes / total_bytes) * 65)
                                    detail = f"已下载 {downloaded_bytes / (1024 * 1024):.2f} / {total_bytes / (1024 * 1024):.2f} MiB"
                                else:
                                    percent = 55
                                    detail = f"已下载 {downloaded_bytes / (1024 * 1024):.2f} MiB"

                                await GalleryArchiver._notify_progress(
                                    progress_callback,
                                    phase="downloading",
                                    percent=percent,
                                    current=downloaded_bytes,
                                    total=total_bytes,
                                    unit="bytes",
                                    detail=detail,
                                )
                    
                    # Verify the file is actually a ZIP
                    await GalleryArchiver._notify_progress(
                        progress_callback,
                        phase="verifying",
                        percent=93,
                        current=None,
                        total=None,
                        unit=None,
                        detail="校验归档文件",
                    )
                    import zipfile
                    try:
                        with zipfile.ZipFile(output_path, 'r') as z:
                            bad = z.testzip()
                            if bad:
                                last_error = f"ZIP file corrupted: {bad}"
                                logger.warning(last_error)
                                continue
                    except zipfile.BadZipFile:
                        # Try to read first bytes to debug
                        async with aiofiles.open(output_path, 'r', encoding='utf-8', errors='ignore') as f:
                            first_bytes = await f.read(200)
                            if '<html' in first_bytes.lower() or '<!doctype' in first_bytes.lower():
                                should_refresh_url = True
                                last_error = "归档下载链接可能已失效，下载结果是 HTML 页面而不是 ZIP"
                            else:
                                last_error = "下载结果不是有效的 ZIP 文件"
                        logger.warning(last_error)
                        continue

                    await GalleryArchiver._notify_progress(
                        progress_callback,
                        phase="packaging",
                        percent=98,
                        current=None,
                        total=None,
                        unit=None,
                        detail="整理归档文件",
                    )
                    
                    logger.info(f"Download completed and verified: {output_path}")
                    return ArchiveDownloadResult(success=True)
                    
            except Exception as e:
                last_error = str(e)
                logger.debug(f"Archive download attempt {attempt + 1} failed: {e}")
        
        # All retries failed
        logger.error(f"Error downloading file after {max_retries} attempts: {last_error}")
        return ArchiveDownloadResult(
            success=False,
            error_msg=last_error or "归档下载失败",
            should_refresh_url=should_refresh_url,
        )
