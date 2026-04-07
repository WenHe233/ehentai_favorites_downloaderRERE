import asyncio
import html as html_mod
from sqlalchemy.future import select
from loguru import logger
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.db.database import SessionLocal
from app.db.models import Gallery, DownloadStatus
from app.core.client import eh_client
from app.core.config import settings
from app.core.parser import EHParser
from app.services.config_service import config_service
from app.services.notification_service import notification_service
from app.services.sync_state import (
    format_sync_timestamp,
    parse_sync_timestamp,
    read_sync_state,
    restore_failed_galleries,
    write_sync_state,
)
from app.services.realtime import realtime_hub

class UpdaterService:
    def __init__(self):
        self._sync_lock = asyncio.Lock()
        self._background_sync_task: Optional[asyncio.Task] = None
        self._last_sync_error: Optional[str] = None

    @property
    def sync_running(self) -> bool:
        task_running = self._background_sync_task is not None and not self._background_sync_task.done()
        return task_running or self._sync_lock.locked()

    @property
    def last_sync_error(self) -> Optional[str]:
        return self._last_sync_error

    def trigger_background_sync(self) -> bool:
        if self.sync_running:
            logger.info("Favorites Sync is already running in the background.")
            return False

        self._last_sync_error = None
        self._background_sync_task = asyncio.create_task(self._run_background_sync())
        return True

    async def _run_background_sync(self) -> None:
        try:
            await self.sync_favorites()
        except Exception as e:
            self._last_sync_error = str(e)
            logger.exception(f"Background Favorites Sync failed: {e}")
        finally:
            current_task = asyncio.current_task()
            if current_task is self._background_sync_task:
                self._background_sync_task = None

    @staticmethod
    async def sync_favorites():
        """
        Main sync loop:
        1. Get monitored favcats from settings
        2. For each favcat, fetch all pages
        3. Parse and upsert into DB
        """
        if updater._sync_lock.locked():
            logger.info("Favorites Sync is already running, skipping duplicate trigger.")
            return False

        async with updater._sync_lock:
            logger.info("Starting Favorites Sync...")
            updater._last_sync_error = None
            await realtime_hub.emit_sync_status(sync_running=True, sync_last_error=None)
            domain = settings.EH_DOMAIN
            monitored_favcats: List[int] = []

            try:
                # Get monitored favcats from dynamic settings
                current_settings = await config_service.get_all_settings()
                sync_state = await read_sync_state()
                sync_state, restored_failed = await restore_failed_galleries(sync_state)
                monitored_favcats = current_settings.get("monitored_favcats")

                # Default to all favcats if not specified
                if not monitored_favcats:
                    monitored_favcats = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

                logger.info(f"Will sync favcats: {monitored_favcats}")

                # Get domain from settings (e-hentai.org or exhentai.org)
                domain = current_settings.get("eh_domain") or settings.EH_DOMAIN
                logger.info(f"Using domain: {domain}")
                if restored_failed:
                    logger.info(f"Re-queued {restored_failed} failed galleries before sync")

                total_processed = 0
                sync_completed = True
                sync_state_changed = False
                start_ts = format_sync_timestamp(datetime.now(timezone.utc))
                oldest_date = UpdaterService._get_oldest_date_threshold(current_settings)

                for favcat in monitored_favcats:
                    logger.info(f"Syncing favcat {favcat}...")
                    since_dt = UpdaterService._effective_since(sync_state, favcat, oldest_date)
                    items, completed = await UpdaterService._scan_category(domain, favcat, since_dt)

                    if items:
                        logger.info(f"Found {len(items)} new galleries for favcat {favcat}")
                    else:
                        logger.info(f"No new galleries found for favcat {favcat}")

                    processed_count, latest_favorited = await UpdaterService._process_items(items)
                    if items:
                        await UpdaterService._refresh_metadata_for_items(items)
                    total_processed += processed_count

                    if completed:
                        if latest_favorited:
                            state_key = str(favcat)
                            previous = parse_sync_timestamp(sync_state["last_favorited"].get(state_key))
                            if previous is None or latest_favorited > previous:
                                sync_state["last_favorited"][state_key] = format_sync_timestamp(latest_favorited)
                                await write_sync_state(sync_state)
                                sync_state_changed = True
                    else:
                        sync_completed = False

                if sync_completed:
                    sync_state["last_run_ts"] = start_ts
                    sync_state_changed = True

                if sync_state_changed:
                    await write_sync_state(sync_state)

                logger.info(f"Favorites Sync completed. Processed {total_processed} items total.")
                await realtime_hub.emit_sync_status(
                    sync_running=False,
                    sync_last_error=None,
                    last_sync_ts=sync_state.get("last_run_ts"),
                )
                await notification_service.notify_sync_completed(
                    domain=domain,
                    monitored_favcats=monitored_favcats,
                    total_processed=total_processed,
                    restored_failed=restored_failed,
                    last_sync_ts=parse_sync_timestamp(sync_state.get("last_run_ts")),
                )
                return True
            except Exception as e:
                updater._last_sync_error = str(e)
                logger.exception(f"Favorites Sync failed: {e}")
                await realtime_hub.emit_sync_status(sync_running=False, sync_last_error=str(e))
                await notification_service.notify_sync_failed(
                    error_msg=str(e),
                    domain=domain,
                    monitored_favcats=monitored_favcats,
                )
                raise

    @staticmethod
    async def _ensure_fav_display_settings(domain: str, favcat: int) -> None:
        """
        Force favorites page to Compact display mode + Favorited Time sort.
        These are sticky server-side settings (one inline_set param per request).
        """
        base = f"https://{domain}/favorites.php?favcat={favcat}"
        try:
            logger.info(f"Setting favorites display mode to Compact for favcat {favcat}")
            await eh_client.get_html(f"{base}&inline_set=dm_l")
        except Exception as e:
            logger.warning(f"Failed to set display mode for favcat {favcat}: {e}")
        try:
            logger.info(f"Setting favorites sort to Favorited Time for favcat {favcat}")
            await eh_client.get_html(f"{base}&inline_set=fs_f")
        except Exception as e:
            logger.warning(f"Failed to set sort order for favcat {favcat}: {e}")

    @staticmethod
    async def _scan_category(domain: str, favcat: int, since_dt: datetime) -> Tuple[List[dict], bool]:
        await UpdaterService._ensure_fav_display_settings(domain, favcat)
        url = f"https://{domain}/favorites.php?favcat={favcat}"
        items: List[dict] = []

        while url:
            try:
                logger.info(f"Fetching: {url}")
                html = await eh_client.get_html(url)
                rows, next_url = EHParser.parse_gallery_list(html)
            except Exception as e:
                logger.error(f"Error syncing favcat {favcat}: {e}")
                return items, False

            if not rows:
                return items, True

            for item in rows:
                item_date = parse_sync_timestamp(item.get("favorited"))
                if item_date and item_date <= since_dt:
                    logger.info(
                        f"Reached sync cutoff for favcat {favcat}: {item_date.strftime('%Y-%m-%d %H:%M')}"
                    )
                    return items, True
                row_payload = dict(item)
                row_payload["favcat"] = favcat
                items.append(row_payload)

            url = next_url

        return items, True

    @staticmethod
    async def _process_items(items: List[dict]) -> Tuple[int, Optional[datetime]]:
        """
        Process gallery items and upsert to database.
        """
        latest_favorited = None

        async with SessionLocal() as session:
            async with session.begin():
                for item in items:
                    gid = item["gid"]
                    token = item["token"]
                    favorited_at = parse_sync_timestamp(item.get("favorited"))
                    if favorited_at and (latest_favorited is None or favorited_at > latest_favorited):
                        latest_favorited = favorited_at
                    
                    stmt = select(Gallery).where(Gallery.gid == gid)
                    result = await session.execute(stmt)
                    existing = result.scalar_one_or_none()
                    
                    if not existing:
                        # New gallery - parse favorited time
                        new_g = Gallery(
                            gid=gid,
                            token=token,
                            title=item["title"],
                            posted=datetime.now(timezone.utc), 
                            filecount=0, 
                            status=DownloadStatus.PENDING,
                            favorited_at=favorited_at,
                            favcat=item.get("favcat"),
                        )
                        session.add(new_g)
                        logger.info(f"New gallery found: {gid} - {item['title'][:50]}")
                    else:
                        if item.get("title") and item["title"] != existing.title:
                            existing.title = item["title"]

                        if favorited_at:
                            existing.favorited_at = favorited_at
                        if item.get("favcat") is not None:
                            existing.favcat = item.get("favcat")
            await session.commit()

        return len(items), latest_favorited

    @staticmethod
    async def _refresh_metadata_for_items(items: List[dict]) -> None:
        if not items:
            return

        chunk_size = 25
        gidlist = []
        seen: set[tuple[int, str]] = set()
        for item in items:
            gid = int(item["gid"])
            token = str(item["token"])
            key = (gid, token)
            if key in seen:
                continue
            seen.add(key)
            gidlist.append([gid, token])

        for index in range(0, len(gidlist), chunk_size):
            payload = {
                "method": "gdata",
                "gidlist": gidlist[index:index + chunk_size],
                "namespace": 1,
            }
            try:
                data = await eh_client.post_api(payload)
                meta_list = data.get("gmetadata", [])
            except Exception as e:
                logger.warning(f"Failed to hydrate metadata for synced galleries: {e}")
                continue

            async with SessionLocal() as session:
                async with session.begin():
                    for meta in meta_list:
                        gid = meta["gid"]
                        token = meta["token"]
                        g = await session.get(Gallery, (gid, token))
                        if not g:
                            continue

                        g.filecount = int(meta.get("filecount") or g.filecount or 0)
                        posted_raw = meta.get("posted")
                        if posted_raw:
                            g.posted = datetime.fromtimestamp(int(posted_raw), tz=timezone.utc)
                        g.tags = meta.get("tags") or g.tags
                        _raw_title = meta.get("title")
                        g.title = html_mod.unescape(_raw_title) if _raw_title else g.title
                        _raw_jpn = meta.get("title_jpn")
                        g.title_jpn = html_mod.unescape(_raw_jpn) if _raw_jpn else g.title_jpn
                        g.category = meta.get("category") or g.category
                        g.uploader = meta.get("uploader") or g.uploader
                        rating = meta.get("rating")
                        if rating is not None:
                            g.rating = float(rating)
                await session.commit()

    @staticmethod
    def _get_oldest_date_threshold(current_settings: dict) -> Optional[datetime]:
        oldest_date_str = current_settings.get("fav_oldest_date")
        fav_tz = current_settings.get("fav_date_timezone")
        if not oldest_date_str:
            return None
        if not fav_tz:
            logger.info("Date filter disabled: timezone not set")
            return None

        try:
            try:
                oldest_date = datetime.strptime(oldest_date_str, "%Y-%m-%d %H:%M")
            except Exception:
                oldest_date = datetime.strptime(oldest_date_str, "%Y-%m-%d")

            if fav_tz == "server":
                import time
                from datetime import timedelta

                offset_hours = -time.timezone / 3600
                oldest_date = oldest_date - timedelta(hours=offset_hours)

            return oldest_date
        except Exception as e:
            logger.warning(f"Failed to parse fav_oldest_date: {e}")
            return None

    @staticmethod
    def _effective_since(sync_state: dict, favcat: int, oldest_date: Optional[datetime]) -> datetime:
        candidates = []
        if oldest_date:
            candidates.append(oldest_date)

        last_favorited = parse_sync_timestamp(sync_state.get("last_favorited", {}).get(str(favcat)))
        if last_favorited:
            candidates.append(last_favorited)

        last_run_ts = parse_sync_timestamp(sync_state.get("last_run_ts"))
        if last_run_ts:
            candidates.append(last_run_ts)

        return max(candidates) if candidates else datetime.min

    @staticmethod
    async def check_updates_via_api():
        """
        Batch check metadata for existing galleries via API.
        Update filecount and posted time.
        Processes in paginated chunks to avoid loading all galleries into memory.
        """
        chunk_size = 25
        offset = 0

        while True:
            async with SessionLocal() as session:
                stmt = select(Gallery).order_by(Gallery.gid).offset(offset).limit(chunk_size)
                result = await session.execute(stmt)
                galleries = result.scalars().all()

            if not galleries:
                break

            offset += len(galleries)

            payload = {
                "method": "gdata",
                "gidlist": [[g.gid, g.token] for g in galleries],
                "namespace": 1
            }

            try:
                data = await eh_client.post_api(payload)
                meta_list = data.get("gmetadata", [])

                async with SessionLocal() as session:
                    async with session.begin():
                        for meta in meta_list:
                            gid = meta["gid"]
                            token = meta["token"]
                            filecount = int(meta["filecount"])
                            posted = datetime.fromtimestamp(int(meta["posted"]), tz=timezone.utc)
                            tags = meta.get("tags", [])

                            g = await session.get(Gallery, (gid, token))
                            if g:
                                if g.filecount != 0 and g.filecount < filecount:
                                    logger.info(f"Update detected for {gid}: {g.filecount} -> {filecount}")
                                    g.status = DownloadStatus.OUTDATED
                                    g.error_msg = "Filecount increased"

                                g.filecount = filecount
                                g.posted = posted
                                g.tags = tags
                                g.title = html_mod.unescape(meta["title"])
                                g.category = meta["category"]
                                g.uploader = meta["uploader"]
                                g.rating = float(meta["rating"])
                                g.last_checked = datetime.now(timezone.utc)

                    await session.commit()
            except Exception as e:
                logger.error(f"API Check failed: {e}")

updater = UpdaterService()
