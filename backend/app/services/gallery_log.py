"""
Gallery log helper for storing per-gallery download logs.
"""
import json
from datetime import datetime
from typing import List, Optional
from loguru import logger

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import SessionLocal
from app.db.models import Gallery


async def _append_gallery_log_with_session(
    session: AsyncSession,
    gid: int,
    token: str,
    entry: dict,
) -> None:
    g = await session.get(Gallery, (gid, token))
    if not g:
        return

    existing = []
    if g.download_logs:
        try:
            existing = json.loads(g.download_logs)
        except Exception:
            existing = []

    existing.append(entry)
    if len(existing) > 100:
        existing = existing[-100:]

    g.download_logs = json.dumps(existing, ensure_ascii=False)
    await session.flush()


async def append_gallery_log(
    gid: int,
    token: str,
    message: str,
    level: str = "info",
    session: Optional[AsyncSession] = None,
):
    """Append a log entry to a gallery's download_logs."""
    try:
        entry = {
            "time": datetime.utcnow().isoformat(),
            "level": level,
            "msg": message
        }

        if session is not None:
            await _append_gallery_log_with_session(session, gid, token, entry)
            return

        async with SessionLocal() as new_session:
            await _append_gallery_log_with_session(new_session, gid, token, entry)
            await new_session.commit()
    except Exception as e:
        logger.warning(f"Failed to append gallery log for {gid}: {e}")


async def clear_gallery_logs(gid: int, token: str):
    """Clear all logs for a gallery."""
    try:
        async with SessionLocal() as session:
            g = await session.get(Gallery, (gid, token))
            if g:
                g.download_logs = None
                await session.commit()
    except Exception as e:
        logger.warning(f"Failed to clear gallery logs for {gid}: {e}")


async def get_gallery_logs(gid: int, token: str) -> List[dict]:
    """Return parsed gallery logs."""
    try:
        async with SessionLocal() as session:
            g = await session.get(Gallery, (gid, token))
            if not g or not g.download_logs:
                return []
            return json.loads(g.download_logs)
    except Exception as e:
        logger.warning(f"Failed to get gallery logs for {gid}: {e}")
        return []
