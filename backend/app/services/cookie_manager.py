"""
E-Hentai Cookie Manager — igneous auto-refresh.

Refreshes the igneous cookie by visiting exhentai.org with existing
ipb_member_id + ipb_pass_hash cookies via httpx.

No browser or extra dependencies required — works on Linux, Docker,
headless servers, or any environment.
"""

import asyncio
import time
from typing import Dict, Optional

import httpx
from loguru import logger

EXHENTAI_URL = "https://exhentai.org/"

# Cooldown: don't attempt refresh more than once per 5 minutes
_REFRESH_COOLDOWN_SECONDS = 300


class CookieRefreshError(Exception):
    """Cookie refresh failed."""


async def _httpx_refresh_igneous(
    ipb_member_id: str,
    ipb_pass_hash: str,
    proxy_url: Optional[str] = None,
) -> Optional[str]:
    """
    Refresh igneous by visiting exhentai.org with existing login cookies.
    Pure httpx — works on any server, no browser required.
    """
    cookies = {
        "ipb_member_id": ipb_member_id,
        "ipb_pass_hash": ipb_pass_hash,
    }
    try:
        async with httpx.AsyncClient(
            cookies=cookies,
            follow_redirects=True,
            timeout=20.0,
            proxy=proxy_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/131.0.0.0 Safari/537.36",
            },
        ) as client:
            resp = await client.get(EXHENTAI_URL)

            # Check if we got sadpanda (invalid session)
            if len(resp.text.strip()) < 100 and "sadpanda" in resp.text.lower():
                logger.warning("Got sadpanda — ipb cookies are invalid, cannot refresh igneous")
                return None

            # Extract igneous from the client cookie jar
            igneous = client.cookies.get("igneous")
            if igneous and igneous not in ("", "mystery", "0"):
                logger.info(f"igneous refreshed via httpx: {igneous}")
                return igneous

            logger.warning("httpx igneous refresh: igneous not found in response cookies")
            return None
    except Exception as e:
        logger.error(f"httpx igneous refresh failed: {e}")
        return None


class CookieManager:
    def __init__(self):
        self._refresh_lock = asyncio.Lock()
        self._last_refresh_time: float = 0.0

    def _is_in_cooldown(self) -> bool:
        return (time.time() - self._last_refresh_time) < _REFRESH_COOLDOWN_SECONDS

    async def refresh_igneous(self, force: bool = False) -> Optional[str]:
        """
        Refresh the igneous cookie using saved ipb cookies from config.
        Returns the new igneous value, or None if refresh is not possible.
        Thread-safe with cooldown. Set force=True to skip cooldown (manual trigger).
        """
        if not force and self._is_in_cooldown():
            logger.info(
                f"Cookie refresh in cooldown "
                f"(last refresh {time.time() - self._last_refresh_time:.0f}s ago)"
            )
            return None

        async with self._refresh_lock:
            # Double-check cooldown after acquiring lock
            if not force and self._is_in_cooldown():
                return None

            from app.core.config import settings as cfg
            cfg.reload()

            if not cfg.COOKIE_AUTO_REFRESH:
                logger.info("Cookie auto-refresh is disabled in config")
                return None

            ipb_member_id = cfg.EH_IPB_MEMBER_ID
            ipb_pass_hash = cfg.EH_IPB_PASS_HASH

            if not ipb_member_id or not ipb_pass_hash:
                logger.warning(
                    "Cannot refresh igneous: ipb_member_id or ipb_pass_hash not configured"
                )
                return None

            proxy_url = cfg.PROXY_URL
            igneous = await _httpx_refresh_igneous(ipb_member_id, ipb_pass_hash, proxy_url)
            self._last_refresh_time = time.time()

            if igneous:
                await self._save_igneous_to_config(igneous)
                return igneous
            else:
                logger.warning("igneous refresh failed — ipb cookies may be expired")
                return None

    async def _save_igneous_to_config(self, igneous: str) -> None:
        """Save igneous to config.yaml and close the EH client."""
        from app.core.config import settings as cfg
        cfg.update_runtime_settings({"igneous": igneous})
        logger.info(f"Saved igneous to config: {igneous}")

        # Close the EH client so it recreates with new cookies on next request
        try:
            from app.core.client import eh_client
            await eh_client.close()
        except Exception as e:
            logger.warning(f"Error closing EHClient after cookie update: {e}")


cookie_manager = CookieManager()
