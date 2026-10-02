import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, update
from sqlalchemy.dialects.sqlite import insert

from app.db.database import SessionLocal
from app.db.models import AppConfig, Gallery, DownloadMode, DownloadStatus

SYNC_STATE_KEY = "sync_state"
SYNC_TS_FORMAT = "%Y-%m-%d %H:%M"
DEFAULT_SYNC_STATE = {
    "last_favorited": {},
    "last_run_ts": None,
    "failed": {},
}
_SYNC_STATE_WRITE_LOCK = asyncio.Lock()


def format_sync_timestamp(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.strftime(SYNC_TS_FORMAT)


def parse_sync_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, SYNC_TS_FORMAT)
    except Exception:
        return None


def normalize_sync_state(raw: Any) -> Dict[str, Any]:
    state = deepcopy(DEFAULT_SYNC_STATE)
    if not isinstance(raw, dict):
        return state

    if isinstance(raw.get("last_favorited"), dict):
        for key, value in raw["last_favorited"].items():
            if value is None or isinstance(value, str):
                state["last_favorited"][str(key)] = value

    if raw.get("last_run_ts") is None or isinstance(raw.get("last_run_ts"), str):
        state["last_run_ts"] = raw.get("last_run_ts")

    if isinstance(raw.get("failed"), dict):
        for gid, info in raw["failed"].items():
            if not isinstance(info, dict):
                continue
            state["failed"][str(gid)] = {
                "token": info.get("token") or "",
                "title": info.get("title") or f"Gallery {gid}",
                "favorited": info.get("favorited"),
                "parent_gid": info.get("parent_gid"),
                "favcat": info.get("favcat"),
                "download_mode": info.get("download_mode") or DownloadMode.ARCHIVE,
            }

    return state


async def _read_sync_state_with_session(session: AsyncSession) -> Dict[str, Any]:
    result = await session.execute(
        select(AppConfig).where(AppConfig.key == SYNC_STATE_KEY)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        return deepcopy(DEFAULT_SYNC_STATE)

    try:
        return normalize_sync_state(json.loads(cfg.value))
    except Exception:
        return deepcopy(DEFAULT_SYNC_STATE)


async def read_sync_state(session: Optional[AsyncSession] = None) -> Dict[str, Any]:
    if session is not None:
        return await _read_sync_state_with_session(session)

    async with SessionLocal() as session:
        return await _read_sync_state_with_session(session)


async def _write_sync_state_with_session(
    session: AsyncSession,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    normalized = normalize_sync_state(state)
    result = await session.execute(
        select(AppConfig).where(AppConfig.key == SYNC_STATE_KEY)
    )
    cfg = result.scalar_one_or_none()
    payload = json.dumps(normalized, ensure_ascii=False)
    if cfg:
        cfg.value = payload
    else:
        session.add(AppConfig(key=SYNC_STATE_KEY, value=payload))
    await session.flush()
    return normalized


async def write_sync_state(
    state: Dict[str, Any],
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    if session is not None:
        return await _write_sync_state_with_session(session, state)

    async with _SYNC_STATE_WRITE_LOCK:
        async with SessionLocal() as session:
            async with session.begin():
                return await _write_sync_state_with_session(session, state)


async def reset_sync_state() -> Dict[str, Any]:
    return await write_sync_state(deepcopy(DEFAULT_SYNC_STATE))


async def write_sync_progress(state: Dict[str, Any]) -> None:
    """Update cursors without overwriting concurrent download retry changes."""
    async with SessionLocal() as session:
        statement = insert(AppConfig).values(key=SYNC_STATE_KEY, value=json.dumps(normalize_sync_state(state)))
        statement = statement.on_conflict_do_update(index_elements=[AppConfig.key], set_={
            "value": func.json_set(AppConfig.value, "$.last_favorited", func.json(json.dumps(state["last_favorited"])), "$.last_run_ts", state.get("last_run_ts"))
        })
        await session.execute(statement)
        await session.commit()


async def _mutate_retry(statement, session=None):
    if session is not None:
        await session.execute(statement)
        return
    async with SessionLocal() as owned:
        await owned.execute(statement)
        await owned.commit()


async def clear_failed_gallery(gid: int, session: Optional[AsyncSession] = None) -> None:
    await _mutate_retry(update(AppConfig).where(AppConfig.key == SYNC_STATE_KEY).values(
        value=func.json_remove(AppConfig.value, f'$.failed."{int(gid)}"')), session)


async def clear_all_failed_galleries() -> None:
    await _mutate_retry(update(AppConfig).where(AppConfig.key == SYNC_STATE_KEY).values(
        value=func.json_set(AppConfig.value, "$.failed", func.json("{}"))))


async def upsert_failed_gallery(gallery: Gallery, session: Optional[AsyncSession] = None) -> None:
    entry = {
        "token": gallery.token or "", "title": gallery.title or f"Gallery {gallery.gid}",
        "favorited": format_sync_timestamp(gallery.favorited_at), "parent_gid": gallery.parent_gid,
        "favcat": gallery.favcat, "download_mode": gallery.download_mode or DownloadMode.ARCHIVE,
    }
    initial = deepcopy(DEFAULT_SYNC_STATE)
    initial["failed"][str(gallery.gid)] = entry
    statement = insert(AppConfig).values(key=SYNC_STATE_KEY, value=json.dumps(initial))
    statement = statement.on_conflict_do_update(index_elements=[AppConfig.key], set_={
        "value": func.json_set(AppConfig.value, f'$.failed."{int(gallery.gid)}"', func.json(json.dumps(entry)))
    })
    await _mutate_retry(statement, session)


async def restore_failed_galleries(
    state: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], int]:
    current_state = normalize_sync_state(state if state is not None else await read_sync_state())
    if not current_state["failed"]:
        return current_state, 0

    restored = 0
    stale_gids = []

    async with SessionLocal() as session:
        async with session.begin():
            for gid_key, info in list(current_state["failed"].items()):
                try:
                    gid = int(gid_key)
                except ValueError:
                    stale_gids.append(gid_key)
                    continue

                result = await session.execute(select(Gallery).where(Gallery.gid == gid))
                existing = result.scalar_one_or_none()

                if existing:
                    if existing.status in [DownloadStatus.COMPLETED, DownloadStatus.ARCHIVED]:
                        stale_gids.append(gid_key)
                        continue

                    if existing.status != DownloadStatus.DOWNLOADING:
                        existing.status = DownloadStatus.PENDING
                        existing.error_msg = None
                        restored += 1
                    continue

                favorited_at = parse_sync_timestamp(info.get("favorited"))
                session.add(
                    Gallery(
                        gid=gid,
                        token=info.get("token") or "",
                        title=info.get("title") or f"Gallery {gid}",
                        category="Retry",
                        posted=favorited_at or datetime.now(timezone.utc),
                        filecount=0,
                        status=DownloadStatus.PENDING,
                        priority=10,
                        download_mode=info.get("download_mode") or DownloadMode.ARCHIVE,
                        favorited_at=favorited_at,
                        parent_gid=info.get("parent_gid"),
                        favcat=info.get("favcat"),
                    )
                )
                restored += 1
        await session.commit()

    if stale_gids:
        for gid_key in stale_gids:
            current_state["failed"].pop(gid_key, None)
        for gid_key in stale_gids:
            try:
                await clear_failed_gallery(int(gid_key))
            except ValueError:
                pass

    return await read_sync_state(), restored
