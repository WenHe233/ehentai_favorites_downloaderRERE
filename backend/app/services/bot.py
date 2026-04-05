import asyncio
import re
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger

from app.core.config import settings
from app.db.database import SessionLocal
from app.services.downloader import downloader
from app.services.manual_queue import queue_manual_gallery

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None
_polling_task: Optional[asyncio.Task] = None


async def _get_runtime_settings() -> dict:
    try:
        from app.services.config_service import config_service

        return await config_service.get_all_settings()
    except Exception as e:
        logger.warning(f"Failed to read runtime settings for bot: {e}")
        return {
            "telegram_bot_token": settings.TELEGRAM_BOT_TOKEN,
            "allowed_telegram_ids": settings.ALLOWED_TELEGRAM_IDS,
            "download_mode": settings.DOWNLOAD_MODE,
        }


def _register_handlers(dispatcher: Dispatcher) -> None:
    @dispatcher.message(Command("start"))
    async def cmd_start(message: Message):
        if not is_allowed(message.from_user.id):
            return
        await message.answer(
            "👋 您好！EH 收藏夹同步助手已就绪。\n"
            "使用 /status 查看系统状态。\n"
            "使用 /download <链接> 下载指定画廊。"
        )

    @dispatcher.message(Command("status"))
    async def cmd_status(message: Message):
        if not is_allowed(message.from_user.id):
            return

        runtime_settings = await _get_runtime_settings()
        status_text = (
            f"🟢 **系统状态**\n"
            f"下载服务: {'运行中' if downloader.is_running else '已停止'}\n"
            f"下载模式: {runtime_settings.get('download_mode') or settings.DOWNLOAD_MODE}\n"
        )
        await message.answer(status_text, parse_mode="Markdown")

    @dispatcher.message(Command("id"))
    async def cmd_id(message: Message):
        await message.answer(f"您的 ID: `{message.from_user.id}`", parse_mode="Markdown")

    @dispatcher.message(Command("download"))
    async def cmd_download(message: Message):
        if not is_allowed(message.from_user.id):
            return

        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "❌ 请提供画廊链接\n"
                "例如: /download https://exhentai.org/g/3708716/efebefd158/\n\n"
                "支持多个链接，用换行或逗号分隔"
            )
            return

        url_candidates = re.split(r"[\n,，]+", args[1])
        url_candidates = [u.strip() for u in url_candidates if u.strip()]
        if not url_candidates:
            await message.answer("❌ 未找到有效的链接")
            return

        valid_urls = []
        for url in url_candidates:
            match = re.search(r"/g/(\d+)/(\w+)/?", url)
            if match:
                valid_urls.append(url)

        if not valid_urls:
            await message.answer("❌ 未找到有效的画廊链接格式")
            return

        await message.answer(f"⏳ 正在处理 {len(valid_urls)} 个链接...")

        try:
            success_count = 0
            exist_count = 0
            detail_lines: list[str] = []

            async with SessionLocal() as db:
                for raw_url in valid_urls:
                    result = await queue_manual_gallery(raw_url, db)
                    if result.status in {"Added", "Queued"}:
                        success_count += 1
                        detail_lines.append(f"✅ {result.message}")
                    elif result.status == "Exists":
                        exist_count += 1
                        detail_lines.append(f"⏭️ {result.message}")

            msg_parts = []
            if success_count > 0:
                msg_parts.append(f"✅ 已添加 {success_count} 个画廊")
            if exist_count > 0:
                msg_parts.append(f"⏭️ 跳过 {exist_count} 个已完成")

            if detail_lines:
                summary = "\n".join(msg_parts) if msg_parts else "处理完成"
                detail_preview = "\n".join(detail_lines[:8])
                if len(detail_lines) > 8:
                    detail_preview += f"\n… 另有 {len(detail_lines) - 8} 条结果"
                await message.answer(f"{summary}\n\n{detail_preview}")
            else:
                await message.answer("\n".join(msg_parts) if msg_parts else "处理完成")
        except Exception as e:
            logger.error(f"Telegram download error: {e}")
            await message.answer(f"❌ 添加失败: {str(e)}")

def is_allowed(user_id: int) -> bool:
    if not settings.ALLOWED_TELEGRAM_IDS:
        return True
    return user_id in settings.ALLOWED_TELEGRAM_IDS

async def start_bot():
    global bot, dp, _polling_task

    if _polling_task and not _polling_task.done():
        logger.info("Telegram Bot is already running.")
        return

    runtime_settings = await _get_runtime_settings()
    token = runtime_settings.get("telegram_bot_token") or settings.TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning("Telegram Token not set. Bot is disabled.")
        return

    settings.ALLOWED_TELEGRAM_IDS = runtime_settings.get("allowed_telegram_ids") or settings.ALLOWED_TELEGRAM_IDS

    bot = Bot(token=token)
    dp = Dispatcher()
    _register_handlers(dp)
    _polling_task = asyncio.current_task()

    logger.info("Starting Telegram Bot polling...")
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Telegram Bot polling cancelled.")
        raise
    except Exception as e:
        logger.error(f"Telegram Bot error: {e}")
    finally:
        if bot:
            await bot.session.close()
        bot = None
        dp = None
        if asyncio.current_task() is _polling_task:
            _polling_task = None

async def stop_bot():
    global bot, dp, _polling_task

    task = _polling_task
    if task and not task.done() and task is not asyncio.current_task():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    if bot:
        await bot.session.close()

    bot = None
    dp = None
    _polling_task = None

