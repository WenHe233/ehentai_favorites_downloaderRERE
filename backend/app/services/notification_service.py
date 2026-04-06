from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Any, Optional, Sequence
from uuid import uuid4

from aiogram import Bot
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import AppConfig, Gallery

NOTIFICATION_BUFFER_KEY = "telegram_notification_buffer"
NOTIFICATION_RETRY_DELAY_SECONDS = 60
BUFFER_REASON_BATCH = "batch"
BUFFER_REASON_QUIET = "quiet"


@dataclass
class TelegramNotificationSettings:
    enabled: bool
    token: Optional[str]
    recipients: list[int]
    timezone_mode: Optional[str]
    on_download_completed: bool
    on_download_failed: bool
    on_download_partial: bool
    on_sync_completed: bool
    on_sync_failed: bool
    batch_window_seconds: int
    quiet_hours_enabled: bool
    quiet_hours_start: Optional[str]
    quiet_hours_end: Optional[str]


@dataclass
class NotificationEvent:
    event_id: str
    kind: str
    created_at: datetime
    title: Optional[str] = None
    gid: Optional[int] = None
    requested_quality: Optional[str] = None
    resolved_quality: Optional[str] = None
    error_msg: Optional[str] = None
    download_path: Optional[str] = None
    downloaded_at: Optional[datetime] = None
    progress_current: Optional[int | float] = None
    progress_total: Optional[int | float] = None
    domain: Optional[str] = None
    monitored_favcats: Optional[list[int]] = None
    total_processed: Optional[int] = None
    restored_failed: Optional[int] = None


@dataclass
class NotificationBufferState:
    events: list[NotificationEvent]
    flush_after: Optional[datetime] = None
    flush_reason: Optional[str] = None


class NotificationService:
    def __init__(self) -> None:
        self._buffer_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._scheduled_flush_at: Optional[datetime] = None

    @staticmethod
    async def _get_runtime_settings() -> TelegramNotificationSettings:
        try:
            from app.services.config_service import config_service

            runtime_settings = await config_service.get_all_settings()
        except Exception as exc:
            logger.warning(f"Failed to read runtime settings for notifications: {exc}")
            runtime_settings = {}

        recipients = list(
            runtime_settings.get("telegram_notification_recipients")
            or settings.TELEGRAM_NOTIFICATION_RECIPIENTS
            or runtime_settings.get("allowed_telegram_ids")
            or settings.ALLOWED_TELEGRAM_IDS
            or []
        )

        quiet_start = runtime_settings.get("telegram_notification_quiet_hours_start")
        quiet_end = runtime_settings.get("telegram_notification_quiet_hours_end")

        return TelegramNotificationSettings(
            enabled=bool(
                runtime_settings.get("telegram_notifications_enabled", settings.TELEGRAM_NOTIFICATIONS_ENABLED)
            ),
            token=runtime_settings.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN,
            recipients=[int(item) for item in recipients if str(item).strip()],
            timezone_mode=runtime_settings.get("fav_date_timezone") or settings.FAV_DATE_TIMEZONE,
            on_download_completed=bool(
                runtime_settings.get(
                    "telegram_notify_download_completed",
                    settings.TELEGRAM_NOTIFY_DOWNLOAD_COMPLETED,
                )
            ),
            on_download_failed=bool(
                runtime_settings.get(
                    "telegram_notify_download_failed",
                    settings.TELEGRAM_NOTIFY_DOWNLOAD_FAILED,
                )
            ),
            on_download_partial=bool(
                runtime_settings.get(
                    "telegram_notify_download_partial",
                    settings.TELEGRAM_NOTIFY_DOWNLOAD_PARTIAL,
                )
            ),
            on_sync_completed=bool(
                runtime_settings.get(
                    "telegram_notify_sync_completed",
                    settings.TELEGRAM_NOTIFY_SYNC_COMPLETED,
                )
            ),
            on_sync_failed=bool(
                runtime_settings.get(
                    "telegram_notify_sync_failed",
                    settings.TELEGRAM_NOTIFY_SYNC_FAILED,
                )
            ),
            batch_window_seconds=max(
                0,
                int(
                    runtime_settings.get(
                        "telegram_notification_batch_window_seconds",
                        settings.TELEGRAM_NOTIFICATION_BATCH_WINDOW_SECONDS,
                    )
                ),
            ),
            quiet_hours_enabled=bool(
                runtime_settings.get(
                    "telegram_notification_quiet_hours_enabled",
                    settings.TELEGRAM_NOTIFICATION_QUIET_HOURS_ENABLED,
                )
            ),
            quiet_hours_start=quiet_start or settings.TELEGRAM_NOTIFICATION_QUIET_HOURS_START,
            quiet_hours_end=quiet_end or settings.TELEGRAM_NOTIFICATION_QUIET_HOURS_END,
        )

    @staticmethod
    def _normalize_datetime(value: Optional[datetime], timezone_mode: Optional[str]) -> Optional[datetime]:
        if value is None:
            return None

        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if timezone_mode == "server":
            return normalized.astimezone()
        return normalized.astimezone(timezone.utc)

    @classmethod
    def _serialize_datetime(cls, value: Optional[datetime]) -> Optional[str]:
        normalized = cls._normalize_datetime(value, None)
        if normalized is None:
            return None
        return normalized.isoformat()

    @staticmethod
    def _deserialize_datetime(value: Any) -> Optional[datetime]:
        if not value or not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None

    @classmethod
    def _format_datetime(cls, value: Optional[datetime], timezone_mode: Optional[str]) -> Optional[str]:
        normalized = cls._normalize_datetime(value, timezone_mode)
        if normalized is None:
            return None
        suffix = "本地时间" if timezone_mode == "server" else "站点时间"
        return f"{normalized.strftime('%Y-%m-%d %H:%M:%S')} ({suffix})"

    @staticmethod
    def _quality_label(value: Optional[str]) -> Optional[str]:
        if value == "original":
            return "原图"
        if value == "native":
            return "展示图"
        return None

    @classmethod
    def _quality_summary(
        cls,
        requested_quality: Optional[str],
        resolved_quality: Optional[str],
    ) -> Optional[str]:
        requested_label = cls._quality_label(requested_quality)
        resolved_label = cls._quality_label(resolved_quality)
        if resolved_label:
            if requested_quality == "original" and resolved_quality == "native":
                return f"质量：{resolved_label}（原图不可用，已自动降级）"
            return f"质量：{resolved_label}"
        if requested_label:
            return f"请求质量：{requested_label}"
        return None

    @staticmethod
    def _format_file_name(download_path: Optional[str]) -> Optional[str]:
        if not download_path:
            return None
        try:
            return Path(download_path).name
        except Exception:
            return download_path

    @staticmethod
    def _format_title(gallery: Gallery) -> str:
        return gallery.title or f"Gallery {gallery.gid}"

    @classmethod
    def _serialize_event(cls, event: NotificationEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "kind": event.kind,
            "created_at": cls._serialize_datetime(event.created_at),
            "title": event.title,
            "gid": event.gid,
            "requested_quality": event.requested_quality,
            "resolved_quality": event.resolved_quality,
            "error_msg": event.error_msg,
            "download_path": event.download_path,
            "downloaded_at": cls._serialize_datetime(event.downloaded_at),
            "progress_current": event.progress_current,
            "progress_total": event.progress_total,
            "domain": event.domain,
            "monitored_favcats": list(event.monitored_favcats or []),
            "total_processed": event.total_processed,
            "restored_failed": event.restored_failed,
        }

    @classmethod
    def _deserialize_event(cls, raw: Any) -> Optional[NotificationEvent]:
        if not isinstance(raw, dict):
            return None

        created_at = cls._deserialize_datetime(raw.get("created_at"))
        if created_at is None:
            return None

        monitored_favcats = raw.get("monitored_favcats")
        if not isinstance(monitored_favcats, list):
            monitored_favcats = None

        return NotificationEvent(
            event_id=str(raw.get("event_id") or uuid4()),
            kind=str(raw.get("kind") or ""),
            created_at=created_at,
            title=raw.get("title"),
            gid=raw.get("gid"),
            requested_quality=raw.get("requested_quality"),
            resolved_quality=raw.get("resolved_quality"),
            error_msg=raw.get("error_msg"),
            download_path=raw.get("download_path"),
            downloaded_at=cls._deserialize_datetime(raw.get("downloaded_at")),
            progress_current=raw.get("progress_current"),
            progress_total=raw.get("progress_total"),
            domain=raw.get("domain"),
            monitored_favcats=monitored_favcats,
            total_processed=raw.get("total_processed"),
            restored_failed=raw.get("restored_failed"),
        )

    async def _read_buffer_state_with_session(
        self,
        session: AsyncSession,
    ) -> NotificationBufferState:
        result = await session.execute(
            select(AppConfig).where(AppConfig.key == NOTIFICATION_BUFFER_KEY)
        )
        cfg = result.scalar_one_or_none()
        if not cfg:
            return NotificationBufferState(events=[])

        try:
            raw = json.loads(cfg.value)
        except Exception:
            logger.warning("Failed to parse persisted Telegram notification buffer, dropping corrupted state.")
            return NotificationBufferState(events=[])

        events: list[NotificationEvent] = []
        if isinstance(raw, dict):
            for item in raw.get("events", []) or []:
                event = self._deserialize_event(item)
                if event is not None:
                    events.append(event)

            flush_reason = raw.get("flush_reason")
            if flush_reason not in {BUFFER_REASON_BATCH, BUFFER_REASON_QUIET}:
                flush_reason = None

            return NotificationBufferState(
                events=events,
                flush_after=self._deserialize_datetime(raw.get("flush_after")),
                flush_reason=flush_reason,
            )

        return NotificationBufferState(events=[])

    async def _write_buffer_state_with_session(
        self,
        session: AsyncSession,
        state: NotificationBufferState,
    ) -> None:
        result = await session.execute(
            select(AppConfig).where(AppConfig.key == NOTIFICATION_BUFFER_KEY)
        )
        cfg = result.scalar_one_or_none()

        if not state.events:
            if cfg is not None:
                await session.delete(cfg)
            await session.flush()
            return

        payload = json.dumps(
            {
                "events": [self._serialize_event(event) for event in state.events],
                "flush_after": self._serialize_datetime(state.flush_after),
                "flush_reason": state.flush_reason,
            },
            ensure_ascii=False,
        )

        if cfg is not None:
            cfg.value = payload
        else:
            session.add(AppConfig(key=NOTIFICATION_BUFFER_KEY, value=payload))
        await session.flush()

    async def _read_buffer_state(self) -> NotificationBufferState:
        async with SessionLocal() as session:
            return await self._read_buffer_state_with_session(session)

    async def _write_buffer_state(self, state: NotificationBufferState) -> None:
        async with SessionLocal() as session:
            async with session.begin():
                await self._write_buffer_state_with_session(session, state)

    @staticmethod
    def _parse_hhmm(value: Optional[str]) -> Optional[time]:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%H:%M").time()
        except Exception:
            return None

    def _is_quiet_hours_active(
        self,
        runtime: TelegramNotificationSettings,
        now: Optional[datetime] = None,
    ) -> bool:
        if not runtime.quiet_hours_enabled:
            return False

        start = self._parse_hhmm(runtime.quiet_hours_start)
        end = self._parse_hhmm(runtime.quiet_hours_end)
        if start is None or end is None or start == end:
            return False

        local_now = (now or datetime.now(timezone.utc)).astimezone()
        current_time = local_now.time()

        if start < end:
            return start <= current_time < end
        return current_time >= start or current_time < end

    def _seconds_until_quiet_end(
        self,
        runtime: TelegramNotificationSettings,
        now: Optional[datetime] = None,
    ) -> int:
        start = self._parse_hhmm(runtime.quiet_hours_start)
        end = self._parse_hhmm(runtime.quiet_hours_end)
        if start is None or end is None or start == end:
            return 0

        local_now = (now or datetime.now(timezone.utc)).astimezone()
        today = local_now.date()
        tzinfo = local_now.tzinfo

        if start < end:
            end_at = datetime.combine(today, end, tzinfo=tzinfo)
        else:
            if local_now.time() >= start:
                end_at = datetime.combine(today + timedelta(days=1), end, tzinfo=tzinfo)
            else:
                end_at = datetime.combine(today, end, tzinfo=tzinfo)

        return max(1, int((end_at - local_now).total_seconds()))

    async def _cancel_flush_task(self) -> None:
        task = self._flush_task
        self._flush_task = None
        self._scheduled_flush_at = None

        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _schedule_flush_at(self, flush_after: datetime) -> None:
        target = self._normalize_datetime(flush_after, None) or datetime.now(timezone.utc)
        if target < datetime.now(timezone.utc):
            target = datetime.now(timezone.utc)

        if self._flush_task and not self._flush_task.done() and self._scheduled_flush_at:
            if self._scheduled_flush_at <= target:
                return
            await self._cancel_flush_task()

        delay_seconds = max(1, ceil((target - datetime.now(timezone.utc)).total_seconds()))
        self._scheduled_flush_at = target
        self._flush_task = asyncio.create_task(self._delayed_flush(delay_seconds))

    async def _send_message(self, text: str, runtime: TelegramNotificationSettings) -> list[int]:
        if not runtime.enabled:
            return []
        if not runtime.token:
            logger.info("Telegram notifications skipped: bot token not configured.")
            return []
        if not runtime.recipients:
            logger.info("Telegram notifications skipped: no recipients configured.")
            return []

        temp_bot: Optional[Bot] = None
        sender: Optional[Bot] = None
        failed_recipients: list[int] = []

        try:
            from app.services import bot as bot_service

            sender = getattr(bot_service, "bot", None)
        except Exception:
            sender = None

        if sender is None:
            temp_bot = Bot(token=runtime.token)
            sender = temp_bot

        try:
            for chat_id in runtime.recipients:
                try:
                    await sender.send_message(chat_id=chat_id, text=text)
                except Exception as exc:
                    logger.warning(f"Failed to send Telegram notification to {chat_id}: {exc}")
                    failed_recipients.append(chat_id)
        finally:
            if temp_bot is not None:
                await temp_bot.session.close()
        return failed_recipients

    @staticmethod
    def _truncate_text(value: Optional[str], limit: int = 44) -> str:
        text = (value or "").strip()
        if not text:
            return "未知"
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1]}…"

    def _format_single_message(self, event: NotificationEvent, runtime: TelegramNotificationSettings) -> str:
        if event.kind == "download_completed":
            lines = [
                "✅ 下载完成",
                f"标题：{self._truncate_text(event.title, 64)}",
                f"GID：{event.gid}",
            ]
            quality_line = self._quality_summary(event.requested_quality, event.resolved_quality)
            if quality_line:
                lines.append(quality_line)
            file_name = self._format_file_name(event.download_path)
            if file_name:
                lines.append(f"文件：{file_name}")
            downloaded_text = self._format_datetime(event.downloaded_at, runtime.timezone_mode)
            if downloaded_text:
                lines.append(f"完成时间：{downloaded_text}")
            return "\n".join(lines)

        if event.kind == "download_failed":
            lines = [
                "❌ 下载失败",
                f"标题：{self._truncate_text(event.title, 64)}",
                f"GID：{event.gid}",
            ]
            quality_line = self._quality_summary(event.requested_quality, event.resolved_quality)
            if quality_line:
                lines.append(quality_line)
            lines.append(f"原因：{event.error_msg or '未知错误'}")
            return "\n".join(lines)

        if event.kind == "download_partial":
            lines = [
                "⚠️ 部分完成",
                f"标题：{self._truncate_text(event.title, 64)}",
                f"GID：{event.gid}",
            ]
            quality_line = self._quality_summary(event.requested_quality, event.resolved_quality)
            if quality_line:
                lines.append(quality_line)
            if event.progress_current is not None and event.progress_total is not None:
                lines.append(f"进度：{event.progress_current}/{event.progress_total}")
            if event.error_msg:
                lines.append(f"说明：{event.error_msg}")
            file_name = self._format_file_name(event.download_path)
            if file_name:
                lines.append(f"部分包：{file_name}")
            return "\n".join(lines)

        if event.kind == "sync_completed":
            lines = [
                "🔄 收藏同步完成",
                f"站点：{event.domain or settings.EH_DOMAIN}",
                "收藏夹："
                + (
                    ", ".join(str(item) for item in (event.monitored_favcats or []))
                    if event.monitored_favcats
                    else "未设置"
                ),
                f"新增或更新：{event.total_processed or 0}",
            ]
            if event.restored_failed:
                lines.append(f"恢复失败任务：{event.restored_failed}")
            completed_text = self._format_datetime(event.created_at, runtime.timezone_mode)
            if completed_text:
                lines.append(f"完成时间：{completed_text}")
            return "\n".join(lines)

        if event.kind == "sync_failed":
            lines = ["⚠️ 收藏同步失败"]
            if event.domain:
                lines.append(f"站点：{event.domain}")
            if event.monitored_favcats:
                lines.append(f"收藏夹：{', '.join(str(item) for item in event.monitored_favcats)}")
            lines.append(f"原因：{event.error_msg or '未知错误'}")
            return "\n".join(lines)

        return "收到一条新的系统提醒。"

    @staticmethod
    def _take_preview(lines: list[str], limit: int = 5) -> list[str]:
        if len(lines) <= limit:
            return lines
        preview = lines[:limit]
        preview.append(f"… 另有 {len(lines) - limit} 条")
        return preview

    def _format_digest_message(
        self,
        events: Sequence[NotificationEvent],
        runtime: TelegramNotificationSettings,
    ) -> str:
        completed = [event for event in events if event.kind == "download_completed"]
        failed = [event for event in events if event.kind == "download_failed"]
        partial = [event for event in events if event.kind == "download_partial"]
        sync_completed = [event for event in events if event.kind == "sync_completed"]
        sync_failed = [event for event in events if event.kind == "sync_failed"]

        start_at = min(event.created_at for event in events)
        end_at = max(event.created_at for event in events)
        lines = [
            "📬 通知摘要",
            f"统计时间：{self._format_datetime(start_at, runtime.timezone_mode)}",
        ]

        if end_at != start_at:
            end_text = self._format_datetime(end_at, runtime.timezone_mode)
            if end_text:
                lines.append(f"截至时间：{end_text}")

        lines.extend(
            [
                f"下载完成：{len(completed)}",
                f"下载失败：{len(failed)}",
                f"部分完成：{len(partial)}",
                f"同步完成：{len(sync_completed)}",
                f"同步失败：{len(sync_failed)}",
            ]
        )

        def add_group(title: str, content_lines: list[str]) -> None:
            if not content_lines:
                return
            lines.append("")
            lines.append(f"{title}：")
            lines.extend(self._take_preview(content_lines))

        add_group(
            "完成任务",
            [
                f"- [{event.gid}] {self._truncate_text(event.title)}"
                + (
                    f"（{self._quality_label(event.resolved_quality) or self._quality_label(event.requested_quality)}）"
                    if self._quality_label(event.resolved_quality) or self._quality_label(event.requested_quality)
                    else ""
                )
                for event in completed
            ],
        )
        add_group(
            "失败任务",
            [
                f"- [{event.gid}] {self._truncate_text(event.title)}：{self._truncate_text(event.error_msg, 36)}"
                for event in failed
            ],
        )
        add_group(
            "部分完成",
            [
                f"- [{event.gid}] {self._truncate_text(event.title)}"
                + (
                    f"（{int(event.progress_current)}/{int(event.progress_total)}）"
                    if event.progress_current is not None and event.progress_total is not None
                    else ""
                )
                for event in partial
            ],
        )
        add_group(
            "同步完成",
            [
                f"- {event.domain or settings.EH_DOMAIN} / "
                f"{','.join(str(item) for item in (event.monitored_favcats or [])) or '未设置'} / "
                f"新增或更新 {event.total_processed or 0}"
                + (f" / 恢复 {event.restored_failed}" if event.restored_failed else "")
                for event in sync_completed
            ],
        )
        add_group(
            "同步失败",
            [
                f"- {(event.domain or settings.EH_DOMAIN)}：{self._truncate_text(event.error_msg, 48)}"
                for event in sync_failed
            ],
        )

        return "\n".join(lines)

    async def _schedule_flush(self, delay_seconds: int) -> None:
        flush_after = datetime.now(timezone.utc) + timedelta(seconds=max(1, delay_seconds))
        await self._schedule_flush_at(flush_after)

    async def _delayed_flush(self, delay_seconds: int) -> None:
        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            return
        finally:
            if self._flush_task is asyncio.current_task():
                self._flush_task = None
                self._scheduled_flush_at = None

        runtime = await self._get_runtime_settings()
        if self._is_quiet_hours_active(runtime):
            await self.refresh_schedule(runtime=runtime)
            return

        await self._flush_pending(runtime)

    async def _flush_pending(self, runtime: Optional[TelegramNotificationSettings] = None) -> None:
        active_runtime = runtime or await self._get_runtime_settings()
        if not active_runtime.enabled or not active_runtime.token or not active_runtime.recipients:
            return

        async with self._buffer_lock:
            state = await self._read_buffer_state()
            if not state.events:
                return
            pending = list(state.events)

        try:
            if len(pending) == 1:
                failed_recipients = await self._send_message(
                    self._format_single_message(pending[0], active_runtime),
                    active_runtime,
                )
            else:
                failed_recipients = await self._send_message(
                    self._format_digest_message(pending, active_runtime),
                    active_runtime,
                )
        except Exception as exc:
            logger.warning(f"Failed to flush Telegram notifications, will retry later: {exc}")
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=NOTIFICATION_RETRY_DELAY_SECONDS)
            async with self._buffer_lock:
                latest_state = await self._read_buffer_state()
                if latest_state.events:
                    latest_state.flush_after = retry_at
                    latest_state.flush_reason = BUFFER_REASON_BATCH
                    await self._write_buffer_state(latest_state)
            await self._schedule_flush_at(retry_at)
            return

        if failed_recipients:
            logger.warning(
                "Telegram notifications were not delivered to all recipients; "
                f"will retry for recipients: {failed_recipients}"
            )
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=NOTIFICATION_RETRY_DELAY_SECONDS)
            async with self._buffer_lock:
                latest_state = await self._read_buffer_state()
                if latest_state.events:
                    latest_state.flush_after = retry_at
                    latest_state.flush_reason = BUFFER_REASON_BATCH
                    await self._write_buffer_state(latest_state)
            await self._schedule_flush_at(retry_at)
            return

        sent_ids = {event.event_id for event in pending}
        async with self._buffer_lock:
            latest_state = await self._read_buffer_state()
            remaining = [event for event in latest_state.events if event.event_id not in sent_ids]
            latest_state.events = remaining
            if not remaining:
                latest_state.flush_after = None
                latest_state.flush_reason = None
            await self._write_buffer_state(latest_state)

        if remaining:
            await self.refresh_schedule(runtime=active_runtime)

    async def _dispatch_event(
        self,
        event: NotificationEvent,
        *,
        runtime: TelegramNotificationSettings,
    ) -> None:
        if not runtime.enabled or not runtime.token or not runtime.recipients:
            return

        if self._is_quiet_hours_active(runtime):
            now = datetime.now(timezone.utc)
            flush_after = now + timedelta(seconds=self._seconds_until_quiet_end(runtime, now))
            async with self._buffer_lock:
                state = await self._read_buffer_state()
                state.events.append(event)
                state.flush_after = flush_after
                state.flush_reason = BUFFER_REASON_QUIET
                await self._write_buffer_state(state)
            await self._schedule_flush_at(flush_after)
            return

        if runtime.batch_window_seconds > 0:
            now = datetime.now(timezone.utc)
            async with self._buffer_lock:
                state = await self._read_buffer_state()
                previous_flush_after = state.flush_after
                previous_reason = state.flush_reason
                state.events.append(event)
                if (
                    previous_reason == BUFFER_REASON_BATCH
                    and previous_flush_after
                    and previous_flush_after > now
                ):
                    state.flush_after = previous_flush_after
                else:
                    state.flush_after = now + timedelta(seconds=runtime.batch_window_seconds)
                state.flush_reason = BUFFER_REASON_BATCH
                await self._write_buffer_state(state)
                flush_after = state.flush_after
            await self._schedule_flush_at(flush_after or now)
            return

        failed_recipients = await self._send_message(self._format_single_message(event, runtime), runtime)
        if failed_recipients:
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=NOTIFICATION_RETRY_DELAY_SECONDS)
            async with self._buffer_lock:
                state = await self._read_buffer_state()
                state.events.append(event)
                state.flush_after = retry_at
                state.flush_reason = BUFFER_REASON_BATCH
                await self._write_buffer_state(state)
            await self._schedule_flush_at(retry_at)

    async def initialize(self) -> int:
        return await self.refresh_schedule()

    async def refresh_schedule(
        self,
        runtime: Optional[TelegramNotificationSettings] = None,
    ) -> int:
        active_runtime = runtime or await self._get_runtime_settings()
        now = datetime.now(timezone.utc)

        async with self._buffer_lock:
            state = await self._read_buffer_state()
            pending_count = len(state.events)
            flush_after = state.flush_after

            if pending_count == 0:
                flush_after = None
            elif active_runtime.enabled and active_runtime.token and active_runtime.recipients:
                if self._is_quiet_hours_active(active_runtime, now):
                    quiet_flush_after = now + timedelta(
                        seconds=self._seconds_until_quiet_end(active_runtime, now)
                    )
                    if (
                        state.flush_reason != BUFFER_REASON_QUIET
                        or state.flush_after != quiet_flush_after
                    ):
                        state.flush_after = quiet_flush_after
                        state.flush_reason = BUFFER_REASON_QUIET
                        await self._write_buffer_state(state)
                    flush_after = quiet_flush_after
                elif (
                    state.flush_reason == BUFFER_REASON_BATCH
                    and state.flush_after
                    and state.flush_after > now
                ):
                    flush_after = state.flush_after
                else:
                    if state.flush_after is not None or state.flush_reason is not None:
                        state.flush_after = None
                        state.flush_reason = None
                        await self._write_buffer_state(state)
                    flush_after = now

        if pending_count == 0 or not active_runtime.enabled or not active_runtime.token or not active_runtime.recipients:
            await self._cancel_flush_task()
            return pending_count

        await self._schedule_flush_at(flush_after or now)
        return pending_count

    async def notify_download_completed(
        self,
        gallery: Gallery,
        *,
        requested_quality: Optional[str] = None,
        resolved_quality: Optional[str] = None,
        downloaded_at: Optional[datetime] = None,
    ) -> None:
        runtime = await self._get_runtime_settings()
        if not runtime.on_download_completed:
            return

        await self._dispatch_event(
            NotificationEvent(
                event_id=str(uuid4()),
                kind="download_completed",
                created_at=downloaded_at or gallery.downloaded_at or datetime.now(timezone.utc),
                title=self._format_title(gallery),
                gid=gallery.gid,
                requested_quality=requested_quality,
                resolved_quality=resolved_quality,
                download_path=gallery.download_path,
                downloaded_at=downloaded_at or gallery.downloaded_at,
            ),
            runtime=runtime,
        )

    async def notify_download_failed(
        self,
        gallery: Gallery,
        *,
        error_msg: Optional[str] = None,
        requested_quality: Optional[str] = None,
        resolved_quality: Optional[str] = None,
    ) -> None:
        runtime = await self._get_runtime_settings()
        if not runtime.on_download_failed:
            return

        await self._dispatch_event(
            NotificationEvent(
                event_id=str(uuid4()),
                kind="download_failed",
                created_at=datetime.now(timezone.utc),
                title=self._format_title(gallery),
                gid=gallery.gid,
                requested_quality=requested_quality,
                resolved_quality=resolved_quality,
                error_msg=error_msg or gallery.error_msg,
                download_path=gallery.download_path,
            ),
            runtime=runtime,
        )

    async def notify_download_partial(
        self,
        gallery: Gallery,
        *,
        error_msg: Optional[str] = None,
        requested_quality: Optional[str] = None,
        resolved_quality: Optional[str] = None,
        progress: Optional[dict] = None,
    ) -> None:
        runtime = await self._get_runtime_settings()
        if not runtime.on_download_partial:
            return

        await self._dispatch_event(
            NotificationEvent(
                event_id=str(uuid4()),
                kind="download_partial",
                created_at=datetime.now(timezone.utc),
                title=self._format_title(gallery),
                gid=gallery.gid,
                requested_quality=requested_quality,
                resolved_quality=resolved_quality,
                error_msg=error_msg or gallery.error_msg,
                download_path=gallery.download_path,
                progress_current=progress.get("current") if progress else None,
                progress_total=progress.get("total") if progress else None,
            ),
            runtime=runtime,
        )

    async def notify_sync_completed(
        self,
        *,
        domain: str,
        monitored_favcats: Sequence[int],
        total_processed: int,
        restored_failed: int,
        last_sync_ts: Optional[datetime] = None,
    ) -> None:
        runtime = await self._get_runtime_settings()
        if not runtime.on_sync_completed:
            return

        await self._dispatch_event(
            NotificationEvent(
                event_id=str(uuid4()),
                kind="sync_completed",
                created_at=last_sync_ts or datetime.now(timezone.utc),
                domain=domain,
                monitored_favcats=list(monitored_favcats),
                total_processed=total_processed,
                restored_failed=restored_failed,
            ),
            runtime=runtime,
        )

    async def notify_sync_failed(
        self,
        *,
        error_msg: str,
        domain: Optional[str] = None,
        monitored_favcats: Optional[Sequence[int]] = None,
    ) -> None:
        runtime = await self._get_runtime_settings()
        if not runtime.on_sync_failed:
            return

        await self._dispatch_event(
            NotificationEvent(
                event_id=str(uuid4()),
                kind="sync_failed",
                created_at=datetime.now(timezone.utc),
                domain=domain,
                monitored_favcats=list(monitored_favcats or []),
                error_msg=error_msg,
            ),
            runtime=runtime,
        )


notification_service = NotificationService()
