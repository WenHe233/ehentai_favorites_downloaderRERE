import httpx
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loguru import logger
from app.core.config import settings
from typing import Optional, Dict, Any
import time
import json

class RateLimiter:
    def __init__(self, interval: float):
        self.interval = interval
        self.last_request_time = 0
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_request_time
            wait_time = self.interval - elapsed
            if wait_time > 0:
                logger.debug(f"RateLimiter: Sleeping for {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
            self.last_request_time = time.time()


async def _get_dynamic_cookies() -> Dict[str, str]:
    """Fetch cookies from DB first, fallback to static settings."""
    try:
        from app.services.config_service import config_service
        db_settings = await config_service.get_all_settings()
        cookies = {
            "ipb_member_id": db_settings.get("ipb_member_id") or settings.EH_IPB_MEMBER_ID,
            "ipb_pass_hash": db_settings.get("ipb_pass_hash") or settings.EH_IPB_PASS_HASH,
            "igneous": db_settings.get("igneous") or settings.EH_IGNEOUS,
        }
        return {k: v for k, v in cookies.items() if v}
    except Exception as e:
        logger.warning(f"Failed to get dynamic cookies, using static: {e}")
        cookies = {
            "ipb_member_id": settings.EH_IPB_MEMBER_ID,
            "ipb_pass_hash": settings.EH_IPB_PASS_HASH,
            "igneous": settings.EH_IGNEOUS,
        }
        return {k: v for k, v in cookies.items() if v}


async def _get_domain() -> str:
    """Get the EH domain from settings (e-hentai.org or exhentai.org)."""
    try:
        from app.services.config_service import config_service
        db_settings = await config_service.get_all_settings()
        return db_settings.get("eh_domain") or settings.EH_DOMAIN
    except Exception:
        return settings.EH_DOMAIN


async def _get_proxy_url() -> Optional[str]:
    try:
        from app.services.config_service import config_service
        db_settings = await config_service.get_all_settings()
        return db_settings.get("proxy_url") or settings.PROXY_URL
    except Exception:
        return settings.PROXY_URL


class EHClient:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self.limiter = RateLimiter(interval=settings.REQUEST_DELAY)
        self._refresh_lock = asyncio.Lock()

    def _get_headers(self):
        return {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def _ensure_client(self):
        """Lazy initialization: create client when first needed, or recreate if closed."""
        if self._client is None or self._client.is_closed:
            logger.info("Creating new httpx client...")
            cookies = await _get_dynamic_cookies()
            proxy_url = await _get_proxy_url()
            logger.debug(f"Using cookies: {list(cookies.keys())}")
            self._client = httpx.AsyncClient(
                cookies=cookies,
                headers=self._get_headers(),
                proxy=proxy_url,
                timeout=30.0,
                follow_redirects=True
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _is_session_expired(self, response: httpx.Response) -> bool:
        """Check if the response indicates an expired/invalid session."""
        # ExHentai sadpanda (blank page or very short response with image)
        if "exhentai.org" in str(response.url):
            body = response.text
            if len(body.strip()) < 100 and "sadpanda" in body.lower():
                return True
            if len(body.strip()) < 50 and "<html" not in body.lower():
                return True

        # Redirect to login page
        final_url = str(response.url)
        if "act=Login" in final_url or "CODE=01" in final_url:
            return True

        return False

    async def _try_auto_refresh(self) -> bool:
        """Attempt to auto-refresh igneous cookie. Returns True if successful."""
        async with self._refresh_lock:
            try:
                from app.services.cookie_manager import cookie_manager
                result = await cookie_manager.refresh_igneous()
                return result is not None
            except Exception as e:
                logger.error(f"Auto-refresh igneous failed: {e}")
                return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException))
    )
    async def get_html(self, url: str, params: Dict = None, _refreshed: bool = False) -> str:
        """
        Fetch HTML with global rate limiting, retries, and session expiration detection.
        If session is expired and auto-refresh is configured, refreshes igneous and retries once.
        """
        await self.limiter.acquire()
        logger.info(f"Fetching: {url}")
        
        client = await self._ensure_client()
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            
            # Basic anti-ban check
            if "banned" in response.text.lower() and "your ip" in response.text.lower():
                logger.critical("Response contains 'banned'! Stopping requests.")
                raise httpx.RequestError("Potential IP Ban detected")

            # Session expiration check — auto-refresh igneous once
            if not _refreshed and self._is_session_expired(response):
                logger.warning(f"Session expired detected for {url}, attempting igneous refresh...")
                refreshed = await self._try_auto_refresh()
                if refreshed:
                    logger.info("igneous refreshed, retrying request...")
                    return await self.get_html(url, params=params, _refreshed=True)
                else:
                    logger.warning("igneous auto-refresh not available or failed")

            return response.text
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            raise

    async def post_api(self, payload: Dict) -> Dict:
        """
        Call https://api.e-hentai.org/api.php
        """
        url = "https://api.e-hentai.org/api.php"
        await self.limiter.acquire()
        
        client = await self._ensure_client()
        logger.debug(f"API Call: {payload}")
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def post_form(self, url: str, data: Dict) -> str:
        """
        Post form data (e.g. for Archiver)
        """
        await self.limiter.acquire()
        logger.info(f"Posting to: {url}")
        
        client = await self._ensure_client()
        response = await client.post(url, data=data)
        response.raise_for_status()
        return response.text

    async def get_account_info(self) -> Dict[str, Any]:
        """
        Fetch GP/Credits from the exchange page.
        """
        try:
            html = await self.get_html("https://e-hentai.org/exchange.php?t=gp")
            import re
            
            # Correct patterns based on actual page structure:
            # "Available: 17,805 kGP" (kGP = thousands of GP)
            # "Available: 49,753,416 Credits"
            
            gp_match = re.search(r'Available:\s*([\d,]+)\s*kGP', html, re.IGNORECASE)
            credits_match = re.search(r'Available:\s*([\d,]+)\s*Credits', html, re.IGNORECASE)
            
            gp_value = None
            credits_value = None
            
            if gp_match:
                # kGP means thousands of GP, multiply by 1000
                gp_value = int(gp_match.group(1).replace(",", "")) * 1000
                
            if credits_match:
                credits_value = int(credits_match.group(1).replace(",", ""))
            
            logger.debug(f"Account info parsed - GP: {gp_value}, Credits: {credits_value}")
            
            return {
                "gp": gp_value,
                "credits": credits_value
            }
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return {"gp": None, "credits": None}

# Process-wide singleton
eh_client = EHClient()
