from copy import deepcopy
from pathlib import Path
import re
import shutil
from typing import Any, Dict, Optional

import yaml
from loguru import logger

from app.core.output_template import (
    OutputTemplateError,
    get_default_filename_max_length,
    normalize_quality_preference,
    validate_output_settings,
)


BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
CONFIG_EXAMPLE_PATH = BASE_DIR / "config.yaml.example"

DEFAULT_CONFIG: Dict[str, Any] = {
    "app": {
        "name": "ehentai_favorites_downloaderRERE",
        "api_v1_str": "/api/v1",
    },
    "paths": {
        "data_dir": "data",
        "download_dir": "downloads",
        "database_url": None,
    },
    "security": {
        "secret_key": "changeme_please_to_something_secure",
        "access_token_expire_minutes": 1440,
        "enable_auth": True,
        "admin_username": "admin",
        "admin_password": "admin",
        "cors_allow_origins": [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
    },
    "auth": {
        "ipb_member_id": None,
        "ipb_pass_hash": None,
        "igneous": None,
        "cookie_auto_refresh": True,
    },
    "site": {
        "domain": "e-hentai.org",
    },
    "network": {
        "proxy_url": None,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "request_delay": 5.0,
    },
    "download": {
        "mode": "archive",
        "archive_quality": "original",
        "max_concurrent_downloads": 3,
        "max_retries": 3,
        "output_template": "./downloads/[{gid}] {title}.zip",
        "conflict_strategy": "rename",
        "truncate_filenames": True,
        "filename_max_length": get_default_filename_max_length(),
    },
    "sync": {
        "interval_minutes": 60,
        "auto_sync": False,
        "monitored_favcats": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        "fav_oldest_date": None,
        "fav_date_timezone": None,
    },
    "telegram": {
        "bot_token": None,
        "allowed_ids": [],
        "notifications": {
            "enabled": False,
            "recipients": [],
            "on_download_completed": True,
            "on_download_failed": True,
            "on_download_partial": True,
            "on_sync_completed": True,
            "on_sync_failed": True,
            "batch_window_seconds": 60,
            "quiet_hours": {
                "enabled": False,
                "start": "23:00",
                "end": "08:00",
            },
        },
    },
}

RUNTIME_UPDATE_PATHS: Dict[str, tuple[str, ...]] = {
    "ipb_member_id": ("auth", "ipb_member_id"),
    "ipb_pass_hash": ("auth", "ipb_pass_hash"),
    "igneous": ("auth", "igneous"),
    "cookie_auto_refresh": ("auth", "cookie_auto_refresh"),
    "eh_domain": ("site", "domain"),
    "download_mode": ("download", "mode"),
    "archive_quality": ("download", "archive_quality"),
    "telegram_bot_token": ("telegram", "bot_token"),
    "allowed_telegram_ids": ("telegram", "allowed_ids"),
    "telegram_notifications_enabled": ("telegram", "notifications", "enabled"),
    "telegram_notification_recipients": ("telegram", "notifications", "recipients"),
    "telegram_notify_download_completed": ("telegram", "notifications", "on_download_completed"),
    "telegram_notify_download_failed": ("telegram", "notifications", "on_download_failed"),
    "telegram_notify_download_partial": ("telegram", "notifications", "on_download_partial"),
    "telegram_notify_sync_completed": ("telegram", "notifications", "on_sync_completed"),
    "telegram_notify_sync_failed": ("telegram", "notifications", "on_sync_failed"),
    "telegram_notification_batch_window_seconds": ("telegram", "notifications", "batch_window_seconds"),
    "telegram_notification_quiet_hours_enabled": ("telegram", "notifications", "quiet_hours", "enabled"),
    "telegram_notification_quiet_hours_start": ("telegram", "notifications", "quiet_hours", "start"),
    "telegram_notification_quiet_hours_end": ("telegram", "notifications", "quiet_hours", "end"),
    "proxy_url": ("network", "proxy_url"),
    "monitored_favcats": ("sync", "monitored_favcats"),
    "fav_oldest_date": ("sync", "fav_oldest_date"),
    "fav_date_timezone": ("sync", "fav_date_timezone"),
    "auto_sync": ("sync", "auto_sync"),
    "max_concurrent_downloads": ("download", "max_concurrent_downloads"),
    "max_retries": ("download", "max_retries"),
    "output_template": ("download", "output_template"),
    "conflict_strategy": ("download", "conflict_strategy"),
    "truncate_filenames": ("download", "truncate_filenames"),
    "filename_max_length": ("download", "filename_max_length"),
}
_PLAIN_SCALAR_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_RESERVED_SCALARS = {"null", "true", "false", "yes", "no", "on", "off", "~"}
_HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_notification_settings(payload: Dict[str, Any]) -> None:
    telegram_cfg = payload.get("telegram") or {}
    notifications_cfg = telegram_cfg.get("notifications") or {}
    quiet_hours_cfg = notifications_cfg.get("quiet_hours") or {}

    batch_window = notifications_cfg.get("batch_window_seconds", 60)
    try:
        batch_window = int(batch_window)
    except (TypeError, ValueError) as exc:
        raise ValueError("telegram.notifications.batch_window_seconds 必须是整数") from exc
    if batch_window < 0:
        raise ValueError("telegram.notifications.batch_window_seconds 不能小于 0")

    for key in ("start", "end"):
        value = _normalize_optional_string(quiet_hours_cfg.get(key))
        if value and not _HHMM_RE.fullmatch(value):
            raise ValueError(f"telegram.notifications.quiet_hours.{key} 必须是 HH:MM 格式")


def _format_yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        if value and _PLAIN_SCALAR_RE.fullmatch(value) and value.lower() not in _RESERVED_SCALARS:
            return value
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"Unsupported YAML scalar type: {type(value)!r}")


def _render_key_value(key: str, value: Any, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, list):
        if not value:
            return [f"{prefix}{key}: []"]
        lines = [f"{prefix}{key}:"]
        for item in value:
            lines.append(f"{prefix}  - {_format_yaml_scalar(item)}")
        return lines
    return [f"{prefix}{key}: {_format_yaml_scalar(value)}"]


def _render_commented_config(payload: Dict[str, Any]) -> str:
    cfg = _deep_merge(DEFAULT_CONFIG, payload)
    lines = [
        "# ehentai_favorites_downloaderRERE 配置文件",
        "#",
        "# 使用说明：",
        "# - 修改后重启后端即可生效。",
        "# - 如果通过设置接口保存，本文件也会被自动回写，并保留注释。",
        "# - `null` 表示未配置。",
        "# - 本文件可能包含敏感信息，请不要提交到公开仓库。",
        "",
        "# 应用显示名称和 API 根路径。通常不需要改动。",
        "app:",
        "  # 应用名称，仅用于界面和日志显示。",
    ]
    lines.extend(_render_key_value("name", cfg["app"]["name"], 1))
    lines.append("  # API 前缀。除非你明确知道影响，否则保持默认。")
    lines.extend(_render_key_value("api_v1_str", cfg["app"]["api_v1_str"], 1))

    lines.extend([
        "",
        "# 本地数据目录设置。相对路径会以 backend 目录为基准。",
        "paths:",
        "  # 数据库、日志等运行数据的目录。",
    ])
    lines.extend(_render_key_value("data_dir", cfg["paths"]["data_dir"], 1))
    lines.append("  # 下载文件保存目录。")
    lines.extend(_render_key_value("download_dir", cfg["paths"]["download_dir"], 1))
    lines.append("  # 数据库连接串。保持 null 时默认使用 data_dir/app.db。")
    lines.extend(_render_key_value("database_url", cfg["paths"]["database_url"], 1))

    lines.extend([
        "",
        "# 安全和管理员配置。",
        "security:",
        "  # 用于签名内部令牌。正式使用时建议改成随机长字符串。",
    ])
    lines.extend(_render_key_value("secret_key", cfg["security"]["secret_key"], 1))
    lines.append("  # 登录令牌过期时间（分钟）。")
    lines.extend(_render_key_value("access_token_expire_minutes", cfg["security"]["access_token_expire_minutes"], 1))
    lines.append("  # 是否开启后台接口登录保护。对外部署时建议开启。")
    lines.extend(_render_key_value("enable_auth", cfg["security"]["enable_auth"], 1))
    lines.append("  # 预留的管理员账号。当前项目主要还是靠本地配置文件管理。")
    lines.extend(_render_key_value("admin_username", cfg["security"]["admin_username"], 1))
    lines.append("  # 预留的管理员密码。若你后续启用登录校验，请务必改掉默认值。")
    lines.extend(_render_key_value("admin_password", cfg["security"]["admin_password"], 1))
    lines.append("  # 允许跨域访问后端的前端地址列表。只部署后端时可留空或仅保留本机地址。")
    lines.extend(_render_key_value("cors_allow_origins", cfg["security"]["cors_allow_origins"], 1))

    lines.extend([
        "",
        "# E-Hentai / ExHentai Cookies。",
        "# ExHentai 通常至少需要 ipb_member_id、ipb_pass_hash、igneous。",
        "auth:",
    ])
    lines.append("  # 登录后的 ipb_member_id。")
    lines.extend(_render_key_value("ipb_member_id", cfg["auth"]["ipb_member_id"], 1))
    lines.append("  # 登录后的 ipb_pass_hash。")
    lines.extend(_render_key_value("ipb_pass_hash", cfg["auth"]["ipb_pass_hash"], 1))
    lines.append("  # ExHentai 访问常用的 igneous cookie。")
    lines.extend(_render_key_value("igneous", cfg["auth"]["igneous"], 1))
    lines.append("  # 是否在 igneous 过期时自动刷新。需要 ipb_member_id 和 ipb_pass_hash。")
    lines.extend(_render_key_value("cookie_auto_refresh", cfg["auth"]["cookie_auto_refresh"], 1))

    lines.extend([
        "",
        "# 站点域名。可选：e-hentai.org / exhentai.org。",
        "site:",
        "  # 一般先保持 e-hentai.org；确认 Cookies 可用后再切到 exhentai.org。",
    ])
    lines.extend(_render_key_value("domain", cfg["site"]["domain"], 1))

    lines.extend([
        "",
        "# 网络相关配置。",
        "network:",
        "  # 代理地址。例如 http://127.0.0.1:7890；不需要时保持 null。",
    ])
    lines.extend(_render_key_value("proxy_url", cfg["network"]["proxy_url"], 1))
    lines.append("  # 请求使用的 User-Agent。一般不需要修改。")
    lines.extend(_render_key_value("user_agent", cfg["network"]["user_agent"], 1))
    lines.append("  # HTML 请求间隔秒数，适当放大更稳妥。")
    lines.extend(_render_key_value("request_delay", cfg["network"]["request_delay"], 1))

    lines.extend([
        "",
        "# 下载策略。",
        "download:",
        "  # 下载模式：archive / native_crawl。",
    ])
    lines.extend(_render_key_value("mode", cfg["download"]["mode"], 1))
    lines.append("  # 下载质量偏好：original / native。归档模式下 native 对应站点的 resample。")
    lines.extend(_render_key_value("archive_quality", cfg["download"]["archive_quality"], 1))
    lines.append("  # 最大并发数。archive 模式指画廊并发，native_crawl 模式指图片并发。")
    lines.extend(_render_key_value("max_concurrent_downloads", cfg["download"]["max_concurrent_downloads"], 1))
    lines.append("  # 单个下载任务失败后的最大重试次数。")
    lines.extend(_render_key_value("max_retries", cfg["download"]["max_retries"], 1))
    lines.append("  # 下载输出模板。相对路径以 backend 目录为基准，允许使用子目录和文件名占位符。")
    lines.extend(_render_key_value("output_template", cfg["download"]["output_template"], 1))
    lines.append("  # 文件冲突处理：rename 自动追加 _1；overwrite 直接覆盖并清理同任务的临时残留。")
    lines.extend(_render_key_value("conflict_strategy", cfg["download"]["conflict_strategy"], 1))
    lines.append("  # 是否在文件名过长时自动截断。")
    lines.extend(_render_key_value("truncate_filenames", cfg["download"]["truncate_filenames"], 1))
    lines.append("  # 文件名最大长度限制。Windows 默认 160，Linux/macOS 默认 220。")
    lines.extend(_render_key_value("filename_max_length", cfg["download"]["filename_max_length"], 1))
    lines.append("  # 可用占位符：{gid} {title} {jpn_title} {category} {uploader} {filecount} {quality}")
    lines.append("  #            {parent_gid} {downloaded_at:%Y-%m-%d} {favorited_at:%Y-%m-%d} {fav}")
    lines.append("  # 扩展名由模板决定。程序实际写入 ZIP 容器，建议使用 .zip 或 .cbz。")

    lines.extend([
        "",
        "# 收藏同步规则。",
        "sync:",
        "  # 自动同步轮询间隔（分钟）。",
    ])
    lines.extend(_render_key_value("interval_minutes", cfg["sync"]["interval_minutes"], 1))
    lines.append("  # 是否在后端启动时自动开启定时同步。")
    lines.extend(_render_key_value("auto_sync", cfg["sync"]["auto_sync"], 1))
    lines.append("  # 需要监控的收藏夹编号，范围 0-9。")
    lines.extend(_render_key_value("monitored_favcats", cfg["sync"]["monitored_favcats"], 1))
    lines.append("  # 仅同步这个时间之后的收藏。格式：YYYY-MM-DD HH:MM；不限制时填 null。")
    lines.extend(_render_key_value("fav_oldest_date", cfg["sync"]["fav_oldest_date"], 1))
    lines.append("  # 时间基准：site 表示站点时区（GMT+0），server 表示本机时区。")
    lines.extend(_render_key_value("fav_date_timezone", cfg["sync"]["fav_date_timezone"], 1))

    lines.extend([
        "",
        "# Telegram Bot 配置。",
        "telegram:",
        "  # BotFather 提供的 bot token；不使用时保持 null。",
    ])
    lines.extend(_render_key_value("bot_token", cfg["telegram"]["bot_token"], 1))
    lines.append("  # 允许使用 bot 的 Telegram 用户 ID 列表。留空时拒绝所有用户，例如 [123456789]。")
    lines.extend(_render_key_value("allowed_ids", cfg["telegram"]["allowed_ids"], 1))
    lines.append("  # 通知提醒设置。通知接收人留空时，会回退到 allowed_ids。")
    lines.append("  notifications:")
    lines.append("    # 是否启用 Telegram 主动提醒。")
    lines.extend(_render_key_value("enabled", cfg["telegram"]["notifications"]["enabled"], 2))
    lines.append("    # 主动提醒接收人列表。留空时使用 allowed_ids。")
    lines.extend(_render_key_value("recipients", cfg["telegram"]["notifications"]["recipients"], 2))
    lines.append("    # 下载完成时发送提醒。")
    lines.extend(_render_key_value("on_download_completed", cfg["telegram"]["notifications"]["on_download_completed"], 2))
    lines.append("    # 下载失败时发送提醒。")
    lines.extend(_render_key_value("on_download_failed", cfg["telegram"]["notifications"]["on_download_failed"], 2))
    lines.append("    # 部分完成（缺页待补抓）时发送提醒。")
    lines.extend(_render_key_value("on_download_partial", cfg["telegram"]["notifications"]["on_download_partial"], 2))
    lines.append("    # 一轮同步完成后发送摘要提醒。")
    lines.extend(_render_key_value("on_sync_completed", cfg["telegram"]["notifications"]["on_sync_completed"], 2))
    lines.append("    # 同步失败时发送提醒。")
    lines.extend(_render_key_value("on_sync_failed", cfg["telegram"]["notifications"]["on_sync_failed"], 2))
    lines.append("    # 批量聚合窗口（秒）。大于 0 时，窗口内多条提醒会合并成一条摘要。")
    lines.extend(_render_key_value("batch_window_seconds", cfg["telegram"]["notifications"]["batch_window_seconds"], 2))
    lines.append("    # 静默时段（按服务器本地时间）。静默期间的提醒会缓存，结束后统一汇总发送。")
    lines.append("    quiet_hours:")
    lines.append("      # 是否启用静默时段。")
    lines.extend(_render_key_value("enabled", cfg["telegram"]["notifications"]["quiet_hours"]["enabled"], 3))
    lines.append("      # 静默开始时间，格式 HH:MM。")
    lines.extend(_render_key_value("start", cfg["telegram"]["notifications"]["quiet_hours"]["start"], 3))
    lines.append("      # 静默结束时间，格式 HH:MM。")
    lines.extend(_render_key_value("end", cfg["telegram"]["notifications"]["quiet_hours"]["end"], 3))
    lines.append("")

    return "\n".join(lines)


class Settings:
    def __init__(self):
        self.BASE_DIR = BASE_DIR
        self.CONFIG_PATH = CONFIG_PATH
        self.CONFIG_EXAMPLE_PATH = CONFIG_EXAMPLE_PATH
        self._raw_config: Dict[str, Any] = {}
        self._config_mtime: float = 0.0
        self.reload()

    def _ensure_config_file(self) -> None:
        if self.CONFIG_PATH.exists():
            return

        if self.CONFIG_EXAMPLE_PATH.exists():
            shutil.copyfile(self.CONFIG_EXAMPLE_PATH, self.CONFIG_PATH)
            return

        self._write_yaml(DEFAULT_CONFIG)

    def _read_yaml(self) -> Dict[str, Any]:
        self._ensure_config_file()
        with self.CONFIG_PATH.open("r", encoding="utf-8") as f:
            payload = yaml.safe_load(f) or {}
        if not isinstance(payload, dict):
            raise ValueError("config.yaml must contain a YAML object at the top level")
        return payload

    def _write_yaml(self, payload: Dict[str, Any]) -> None:
        with self.CONFIG_PATH.open("w", encoding="utf-8") as f:
            f.write(_render_commented_config(payload))

    def _resolve_path(self, value: Any, default_name: str) -> Path:
        raw = _normalize_optional_string(value)
        path = Path(raw) if raw else (self.BASE_DIR / default_name)
        if not path.is_absolute():
            path = self.BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _apply(self, config_data: Dict[str, Any]) -> None:
        self._raw_config = config_data

        app_cfg = config_data["app"]
        paths_cfg = config_data["paths"]
        security_cfg = config_data["security"]
        auth_cfg = config_data["auth"]
        site_cfg = config_data["site"]
        network_cfg = config_data["network"]
        download_cfg = config_data["download"]
        sync_cfg = config_data["sync"]
        telegram_cfg = config_data["telegram"]
        telegram_notifications_cfg = telegram_cfg.get("notifications") or {}
        telegram_quiet_hours_cfg = telegram_notifications_cfg.get("quiet_hours") or {}

        self.APP_NAME = app_cfg["name"]
        self.API_V1_STR = app_cfg["api_v1_str"]

        self.DATA_DIR = self._resolve_path(paths_cfg.get("data_dir"), "data")
        self.DOWNLOAD_DIR = self._resolve_path(paths_cfg.get("download_dir"), "downloads")

        database_url = _normalize_optional_string(paths_cfg.get("database_url"))
        self.DATABASE_URL = database_url or f"sqlite+aiosqlite:///{self.DATA_DIR / 'app.db'}"

        self.SECRET_KEY = security_cfg["secret_key"]
        self.ACCESS_TOKEN_EXPIRE_MINUTES = int(security_cfg["access_token_expire_minutes"])
        self.ENABLE_AUTH = bool(security_cfg.get("enable_auth"))
        self.ADMIN_USERNAME = security_cfg["admin_username"]
        self.ADMIN_PASSWORD = security_cfg["admin_password"]
        self.CORS_ALLOW_ORIGINS = [
            str(origin).strip()
            for origin in (security_cfg.get("cors_allow_origins") or [])
            if str(origin).strip()
        ]

        self.EH_IPB_MEMBER_ID = _normalize_optional_string(auth_cfg.get("ipb_member_id"))
        self.EH_IPB_PASS_HASH = _normalize_optional_string(auth_cfg.get("ipb_pass_hash"))
        self.EH_IGNEOUS = _normalize_optional_string(auth_cfg.get("igneous"))
        self.COOKIE_AUTO_REFRESH = bool(auth_cfg.get("cookie_auto_refresh", True))

        self.EH_DOMAIN = site_cfg["domain"]

        self.PROXY_URL = _normalize_optional_string(network_cfg.get("proxy_url"))
        self.USER_AGENT = network_cfg["user_agent"]
        self.REQUEST_DELAY = float(network_cfg["request_delay"])

        configured_download_mode = str(download_cfg["mode"]).strip()
        if configured_download_mode == "crawl":
            configured_download_mode = "native_crawl"
        if configured_download_mode not in {"archive", "native_crawl"}:
            configured_download_mode = "archive"

        configured_quality = normalize_quality_preference(download_cfg.get("archive_quality"))
        conflict_strategy = str(download_cfg.get("conflict_strategy") or "").strip().lower() or "rename"
        if conflict_strategy not in {"rename", "overwrite"}:
            conflict_strategy = "rename"
        truncate_filenames = bool(download_cfg.get("truncate_filenames", True))
        try:
            filename_max_length = int(download_cfg.get("filename_max_length", get_default_filename_max_length()))
        except (TypeError, ValueError):
            filename_max_length = get_default_filename_max_length()
        output_template = str(download_cfg.get("output_template") or "./downloads/[{gid}] {title}.zip").strip()

        validate_output_settings(
            template=output_template,
            conflict_strategy=conflict_strategy,
            truncate_enabled=truncate_filenames,
            max_length=filename_max_length,
        )
        _validate_notification_settings(config_data)

        self.DOWNLOAD_MODE = configured_download_mode
        self.ARCHIVE_QUALITY = configured_quality
        self.MAX_CONCURRENT_DOWNLOADS = int(download_cfg["max_concurrent_downloads"])
        self.MAX_RETRIES = int(download_cfg["max_retries"])
        self.OUTPUT_TEMPLATE = output_template
        self.CONFLICT_STRATEGY = conflict_strategy
        self.TRUNCATE_FILENAMES = truncate_filenames
        self.FILENAME_MAX_LENGTH = filename_max_length

        self.SYNC_INTERVAL_MINUTES = int(sync_cfg["interval_minutes"])
        self.AUTO_SYNC = bool(sync_cfg["auto_sync"])
        self.MONITORED_FAVCATS = [int(x) for x in (sync_cfg.get("monitored_favcats") or [])]
        self.FAV_OLDEST_DATE = _normalize_optional_string(sync_cfg.get("fav_oldest_date"))
        self.FAV_DATE_TIMEZONE = _normalize_optional_string(sync_cfg.get("fav_date_timezone"))

        self.TELEGRAM_BOT_TOKEN = _normalize_optional_string(telegram_cfg.get("bot_token"))
        self.ALLOWED_TELEGRAM_IDS = [int(x) for x in (telegram_cfg.get("allowed_ids") or [])]
        self.TELEGRAM_NOTIFICATIONS_ENABLED = bool(telegram_notifications_cfg.get("enabled", False))
        self.TELEGRAM_NOTIFICATION_RECIPIENTS = [
            int(x) for x in (telegram_notifications_cfg.get("recipients") or []) if str(x).strip()
        ]
        self.TELEGRAM_NOTIFY_DOWNLOAD_COMPLETED = bool(
            telegram_notifications_cfg.get("on_download_completed", True)
        )
        self.TELEGRAM_NOTIFY_DOWNLOAD_FAILED = bool(
            telegram_notifications_cfg.get("on_download_failed", True)
        )
        self.TELEGRAM_NOTIFY_DOWNLOAD_PARTIAL = bool(
            telegram_notifications_cfg.get("on_download_partial", True)
        )
        self.TELEGRAM_NOTIFY_SYNC_COMPLETED = bool(
            telegram_notifications_cfg.get("on_sync_completed", True)
        )
        self.TELEGRAM_NOTIFY_SYNC_FAILED = bool(
            telegram_notifications_cfg.get("on_sync_failed", True)
        )
        self.TELEGRAM_NOTIFICATION_BATCH_WINDOW_SECONDS = max(
            0,
            int(telegram_notifications_cfg.get("batch_window_seconds", 60)),
        )
        self.TELEGRAM_NOTIFICATION_QUIET_HOURS_ENABLED = bool(
            telegram_quiet_hours_cfg.get("enabled", False)
        )
        self.TELEGRAM_NOTIFICATION_QUIET_HOURS_START = _normalize_optional_string(
            telegram_quiet_hours_cfg.get("start")
        ) or "23:00"
        self.TELEGRAM_NOTIFICATION_QUIET_HOURS_END = _normalize_optional_string(
            telegram_quiet_hours_cfg.get("end")
        ) or "08:00"

    def reload(self, force: bool = False) -> Dict[str, Any]:
        if not force and self._raw_config:
            try:
                current_mtime = self.CONFIG_PATH.stat().st_mtime
                if current_mtime == self._config_mtime:
                    return deepcopy(self._raw_config)
            except OSError:
                pass
        config_data = _deep_merge(DEFAULT_CONFIG, self._read_yaml())
        # Auto-generate a random secret_key if user hasn't changed the default
        security_cfg = config_data.get("security", {})
        config_changed = False
        if security_cfg.get("secret_key") == "changeme_please_to_something_secure":
            import secrets as _secrets
            new_key = _secrets.token_urlsafe(48)
            security_cfg["secret_key"] = new_key
            config_changed = True
        # Auto-generate a random admin password if still using default
        if security_cfg.get("admin_password") == "admin" and security_cfg.get("enable_auth", True):
            import secrets as _secrets
            new_password = _secrets.token_urlsafe(16)
            security_cfg["admin_password"] = new_password
            config_changed = True
            logger.warning(
                f"Default admin password detected. Auto-generated new password: {new_password}  "
                "Please save this password or change it in config.yaml."
            )
        if config_changed:
            self._write_yaml(config_data)
        self._apply(config_data)
        try:
            self._config_mtime = self.CONFIG_PATH.stat().st_mtime
        except OSError:
            self._config_mtime = 0.0
        return deepcopy(self._raw_config)

    def _set_nested(self, payload: Dict[str, Any], path: tuple[str, ...], value: Any) -> None:
        current: Dict[str, Any] = payload
        for key in path[:-1]:
            current.setdefault(key, {})
            current = current[key]
        current[path[-1]] = value

    def update_runtime_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        config_data = _deep_merge(DEFAULT_CONFIG, self._read_yaml())
        for key, value in updates.items():
            if key not in RUNTIME_UPDATE_PATHS:
                continue
            if key == "download_mode":
                value = str(value).strip()
                if value == "crawl":
                    value = "native_crawl"
                if value not in {"archive", "native_crawl"}:
                    value = "archive"
            if key == "archive_quality":
                value = normalize_quality_preference(value)
            self._set_nested(config_data, RUNTIME_UPDATE_PATHS[key], value)
        download_cfg = config_data.setdefault("download", {})
        validate_output_settings(
            template=download_cfg.get("output_template"),
            conflict_strategy=download_cfg.get("conflict_strategy"),
            truncate_enabled=bool(download_cfg.get("truncate_filenames", True)),
            max_length=download_cfg.get("filename_max_length", get_default_filename_max_length()),
        )
        _validate_notification_settings(config_data)
        self._write_yaml(config_data)
        self.reload(force=True)
        return self.get_runtime_settings()

    def get_runtime_settings(self) -> Dict[str, Any]:
        return {
            "ipb_member_id": self.EH_IPB_MEMBER_ID,
            "ipb_pass_hash": self.EH_IPB_PASS_HASH,
            "igneous": self.EH_IGNEOUS,
            "cookie_auto_refresh": self.COOKIE_AUTO_REFRESH,
            "eh_domain": self.EH_DOMAIN,
            "download_mode": self.DOWNLOAD_MODE,
            "archive_quality": self.ARCHIVE_QUALITY,
            "telegram_bot_token": self.TELEGRAM_BOT_TOKEN,
            "allowed_telegram_ids": list(self.ALLOWED_TELEGRAM_IDS),
            "telegram_notifications_enabled": self.TELEGRAM_NOTIFICATIONS_ENABLED,
            "telegram_notification_recipients": list(self.TELEGRAM_NOTIFICATION_RECIPIENTS),
            "telegram_notify_download_completed": self.TELEGRAM_NOTIFY_DOWNLOAD_COMPLETED,
            "telegram_notify_download_failed": self.TELEGRAM_NOTIFY_DOWNLOAD_FAILED,
            "telegram_notify_download_partial": self.TELEGRAM_NOTIFY_DOWNLOAD_PARTIAL,
            "telegram_notify_sync_completed": self.TELEGRAM_NOTIFY_SYNC_COMPLETED,
            "telegram_notify_sync_failed": self.TELEGRAM_NOTIFY_SYNC_FAILED,
            "telegram_notification_batch_window_seconds": self.TELEGRAM_NOTIFICATION_BATCH_WINDOW_SECONDS,
            "telegram_notification_quiet_hours_enabled": self.TELEGRAM_NOTIFICATION_QUIET_HOURS_ENABLED,
            "telegram_notification_quiet_hours_start": self.TELEGRAM_NOTIFICATION_QUIET_HOURS_START,
            "telegram_notification_quiet_hours_end": self.TELEGRAM_NOTIFICATION_QUIET_HOURS_END,
            "proxy_url": self.PROXY_URL,
            "monitored_favcats": list(self.MONITORED_FAVCATS),
            "fav_oldest_date": self.FAV_OLDEST_DATE,
            "fav_date_timezone": self.FAV_DATE_TIMEZONE,
            "auto_sync": self.AUTO_SYNC,
            "max_concurrent_downloads": self.MAX_CONCURRENT_DOWNLOADS,
            "max_retries": self.MAX_RETRIES,
            "output_template": self.OUTPUT_TEMPLATE,
            "conflict_strategy": self.CONFLICT_STRATEGY,
            "truncate_filenames": self.TRUNCATE_FILENAMES,
            "filename_max_length": self.FILENAME_MAX_LENGTH,
        }


settings = Settings()
