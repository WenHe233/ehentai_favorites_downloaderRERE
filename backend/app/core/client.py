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


class EHClient:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self.limiter = RateLimiter(interval=settings.REQUEST_DELAY)

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
            logger.debug(f"Using cookies: {list(cookies.keys())}")
            self._client = httpx.AsyncClient(
                cookies=cookies,
                headers=self._get_headers(),
                proxy=settings.PROXY_URL,
                timeout=30.0,
                follow_redirects=True
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException))
    )
    async def get_html(self, url: str, params: Dict = None) -> str:
        """
        Fetch HTML with global rate limiting and retries.
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
