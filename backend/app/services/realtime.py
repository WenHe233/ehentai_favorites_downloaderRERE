import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional


TERMINAL_PHASES = {"completed", "partial", "failed", "cancelled"}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_progress(progress: Dict[str, Any]) -> Dict[str, Any]:
    percent = float(progress.get("percent", 0))
    percent = max(0.0, min(100.0, percent))

    current = progress.get("current")
    total = progress.get("total")

    if isinstance(current, bool):
        current = int(current)
    if isinstance(total, bool):
        total = int(total)

    if current is not None:
        current = float(current)
        if current.is_integer():
            current = int(current)

    if total is not None:
        total = float(total)
        if total.is_integer():
            total = int(total)

    normalized = {
        "phase": str(progress.get("phase") or "queued"),
        "percent": round(percent, 2),
        "current": current,
        "total": total,
        "unit": progress.get("unit"),
        "detail": str(progress.get("detail") or ""),
        "updated_at": progress.get("updated_at") or utcnow_iso(),
    }
    return normalized


def fallback_progress(status: str, error_msg: Optional[str] = None) -> Dict[str, Any]:
    normalized_status = (status or "").lower()

    if normalized_status in {"completed", "archived"}:
        return normalize_progress(
            {
                "phase": "completed",
                "percent": 100,
                "detail": "下载完成",
            }
        )

    if normalized_status == "partial":
        return normalize_progress(
            {
                "phase": "partial",
                "percent": 0,
                "detail": error_msg or "部分下载完成，等待补抓",
            }
        )

    if normalized_status == "failed":
        return normalize_progress(
            {
                "phase": "failed",
                "percent": 0,
                "detail": error_msg or "下载失败",
            }
        )

    if normalized_status == "downloading":
        return normalize_progress(
            {
                "phase": "preparing",
                "percent": 5,
                "detail": "下载任务进行中",
            }
        )

    if normalized_status == "outdated":
        return normalize_progress(
            {
                "phase": "queued",
                "percent": 0,
                "detail": "等待重新下载",
            }
        )

    return normalize_progress(
        {
            "phase": "queued",
            "percent": 0,
            "detail": "等待下载",
        }
    )


def format_sse_event(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class RealtimeHub:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()
        self._gallery_entries: Dict[int, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def _publish(self, event: str, payload: Dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers)

        message = {
            "event": event,
            "payload": payload,
        }

        for queue in subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                continue

    async def set_gallery_progress(
        self,
        gid: int,
        *,
        title: Optional[str] = None,
        status: Optional[str] = None,
        requested_quality: Optional[str] = None,
        resolved_quality: Optional[str] = None,
        progress: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = normalize_progress(progress)

        async with self._lock:
            entry = deepcopy(self._gallery_entries.get(gid, {"gid": gid}))
            entry["gid"] = gid
            if title is not None:
                entry["title"] = title
            if status is not None:
                entry["status"] = status
            if requested_quality is not None:
                entry["requested_quality"] = requested_quality
            if resolved_quality is not None:
                entry["resolved_quality"] = resolved_quality
            entry["progress"] = normalized
            self._gallery_entries[gid] = entry
            payload = deepcopy(entry)

        await self._publish("gallery_progress", payload)
        return normalized

    async def emit_gallery_status(
        self,
        gid: int,
        *,
        status: str,
        title: Optional[str] = None,
        error_msg: Optional[str] = None,
        downloaded_at: Optional[str] = None,
        requested_quality: Optional[str] = None,
        resolved_quality: Optional[str] = None,
        progress: Optional[Dict[str, Any]] = None,
    ) -> None:
        resolved_progress = normalize_progress(
            progress or fallback_progress(status=status, error_msg=error_msg)
        )

        async with self._lock:
            entry = deepcopy(self._gallery_entries.get(gid, {"gid": gid}))
            entry["gid"] = gid
            entry["status"] = status
            if title is not None:
                entry["title"] = title
            if requested_quality is not None:
                entry["requested_quality"] = requested_quality
            if resolved_quality is not None:
                entry["resolved_quality"] = resolved_quality
            entry["progress"] = resolved_progress
            payload = deepcopy(entry)
            payload["error_msg"] = error_msg
            payload["downloaded_at"] = downloaded_at
            self._gallery_entries.pop(gid, None)

        await self._publish("gallery_status", payload)

    async def emit_cancelled(self, gid: int, *, title: Optional[str] = None) -> None:
        await self.emit_gallery_status(
            gid,
            status="cancelled",
            title=title,
            progress={
                "phase": "cancelled",
                "percent": 0,
                "detail": "下载已取消",
            },
        )

    async def emit_sync_status(
        self,
        *,
        sync_running: Optional[bool] = None,
        sync_last_error: Optional[str] = None,
        last_sync_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.services.sync_state import read_sync_state
        from app.services.updater import updater

        sync_state = await read_sync_state()
        payload = {
            "sync_running": updater.sync_running if sync_running is None else sync_running,
            "sync_last_error": updater.last_sync_error if sync_last_error is None else sync_last_error,
            "last_sync_ts": sync_state.get("last_run_ts") if last_sync_ts is None else last_sync_ts,
            "updated_at": utcnow_iso(),
        }
        await self._publish("sync_status", payload)
        return payload

    async def get_gallery_progress_map(self) -> Dict[int, Dict[str, Any]]:
        async with self._lock:
            return {
                gid: deepcopy(entry["progress"])
                for gid, entry in self._gallery_entries.items()
                if entry.get("progress")
            }

    async def clear_gallery(self, gid: int) -> None:
        async with self._lock:
            self._gallery_entries.pop(gid, None)

    async def clear_all(self) -> None:
        async with self._lock:
            self._gallery_entries.clear()

    async def build_snapshot(self) -> Dict[str, Any]:
        from app.services.downloader import downloader
        from app.services.sync_state import read_sync_state
        from app.services.updater import updater

        sync_state = await read_sync_state()
        async with self._lock:
            active_galleries = [
                deepcopy(entry)
                for entry in self._gallery_entries.values()
            ]

        active_galleries.sort(key=lambda item: item.get("gid", 0), reverse=True)
        return {
            "active_galleries": active_galleries,
            "sync_status": {
                "sync_running": updater.sync_running,
                "sync_last_error": updater.last_sync_error,
                "last_sync_ts": sync_state.get("last_run_ts"),
                "updated_at": utcnow_iso(),
            },
            "downloader_running": downloader.is_running,
            "updated_at": utcnow_iso(),
        }


realtime_hub = RealtimeHub()
