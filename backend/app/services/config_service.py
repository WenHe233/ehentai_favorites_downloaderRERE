from app.core.config import settings
import asyncio
from loguru import logger

SECRET_FIELDS = {"ipb_member_id", "ipb_pass_hash", "igneous", "telegram_bot_token"}

class ConfigService:
    @staticmethod
    async def get_all_settings():
        settings.reload()
        return settings.get_runtime_settings()

    @staticmethod
    async def get_public_settings():
        settings_payload = await ConfigService.get_all_settings()
        public_settings = dict(settings_payload)

        for field in SECRET_FIELDS:
            public_settings[f"{field}_configured"] = bool(settings_payload.get(field))
            public_settings[field] = ""

        return public_settings

    @staticmethod
    async def update_settings(new_settings: dict):
        sanitized_settings = dict(new_settings)
        for field in SECRET_FIELDS:
            if sanitized_settings.get(field, None) == "":
                sanitized_settings.pop(field, None)

        if not sanitized_settings:
            return

        old_settings = await ConfigService.get_all_settings()
        old_token = old_settings.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN
        old_auto_sync = bool(old_settings.get("auto_sync"))

        settings.update_runtime_settings(sanitized_settings)

        # 2. Reload EHClient - close it, lazy init will recreate on next use
        try:
            from app.core.client import eh_client
            await eh_client.close()
            logger.info("EHClient closed, will recreate on next request.")
        except Exception as e:
            logger.error(f"Error closing EHClient: {e}")

        # 3. Scheduler - start/stop when auto sync changes
        if "auto_sync" in sanitized_settings:
            current_auto_sync = bool(sanitized_settings["auto_sync"])
            if current_auto_sync != old_auto_sync:
                try:
                    from app.services.scheduler import start_scheduler, stop_scheduler

                    if current_auto_sync:
                        start_scheduler()
                    else:
                        stop_scheduler()
                except Exception as e:
                    logger.error(f"Error toggling scheduler: {e}")
        
        # 4. Bot - Restart if token changed (lazy import)
        if "telegram_bot_token" in sanitized_settings:
            current_token = sanitized_settings["telegram_bot_token"]
            if current_token != old_token:
                logger.info("Bot token changed, will restart bot...")
                try:
                    from app.services.bot import stop_bot, start_bot
                    await stop_bot()
                    if current_token:
                        asyncio.create_task(start_bot())
                except Exception as e:
                    logger.error(f"Error restarting bot: {e}")

        notification_related_fields = {
            "telegram_bot_token",
            "allowed_telegram_ids",
            "telegram_notifications_enabled",
            "telegram_notification_recipients",
            "telegram_notify_download_completed",
            "telegram_notify_download_failed",
            "telegram_notify_download_partial",
            "telegram_notify_sync_completed",
            "telegram_notify_sync_failed",
            "telegram_notification_batch_window_seconds",
            "telegram_notification_quiet_hours_enabled",
            "telegram_notification_quiet_hours_start",
            "telegram_notification_quiet_hours_end",
        }
        if notification_related_fields.intersection(sanitized_settings):
            try:
                from app.services.notification_service import notification_service

                await notification_service.refresh_schedule()
            except Exception as e:
                logger.error(f"Error refreshing notification schedule: {e}")

config_service = ConfigService()
