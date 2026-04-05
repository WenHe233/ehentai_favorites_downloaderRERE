import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, List

from sqlalchemy import text


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.services.maintenance import get_legacy_state  # noqa: E402


DEFAULT_SECRET_KEYS = {
    "changeme_please_to_something_secure",
    "dev_secret_key_123",
}
DEFAULT_ADMIN_CREDENTIALS = {("admin", "admin")}


def add_result(results: List[Dict[str, str]], name: str, status: str, detail: str) -> None:
    results.append({"name": name, "status": status, "detail": detail})


def probe_writable_directory(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path, delete=True) as tmp:
        tmp.write(b"ok")
        tmp.flush()
    return True


async def run_checks() -> List[Dict[str, str]]:
    settings.reload()
    results: List[Dict[str, str]] = []

    config_exists = settings.CONFIG_PATH.exists()
    add_result(
        results,
        "config_file",
        "PASS" if config_exists else "FAIL",
        str(settings.CONFIG_PATH),
    )

    try:
        probe_writable_directory(settings.DATA_DIR)
        add_result(results, "data_dir", "PASS", str(settings.DATA_DIR))
    except Exception as exc:
        add_result(results, "data_dir", "FAIL", f"{settings.DATA_DIR}: {exc}")

    try:
        probe_writable_directory(settings.DOWNLOAD_DIR)
        add_result(results, "download_dir", "PASS", str(settings.DOWNLOAD_DIR))
    except Exception as exc:
        add_result(results, "download_dir", "FAIL", f"{settings.DOWNLOAD_DIR}: {exc}")

    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        add_result(results, "database", "PASS", settings.DATABASE_URL)
    except Exception as exc:
        add_result(results, "database", "FAIL", str(exc))

    if settings.EH_IPB_MEMBER_ID and settings.EH_IPB_PASS_HASH:
        add_result(results, "cookies_basic", "PASS", "ipb_member_id / ipb_pass_hash 已配置")
    else:
        add_result(results, "cookies_basic", "FAIL", "缺少 ipb_member_id 或 ipb_pass_hash")

    if settings.EH_DOMAIN == "exhentai.org" and not settings.EH_IGNEOUS:
        add_result(results, "igneous", "FAIL", "当前域名为 exhentai.org，但未配置 igneous")
    elif settings.EH_IGNEOUS:
        add_result(results, "igneous", "PASS", "igneous 已配置")
    else:
        add_result(results, "igneous", "WARN", "未配置 igneous；普通站可用，里站通常不够")

    auth_enabled = bool(settings.ENABLE_AUTH)
    if settings.SECRET_KEY in DEFAULT_SECRET_KEYS:
        status = "FAIL" if auth_enabled else "WARN"
        add_result(results, "secret_key", status, "仍在使用默认/演示 secret_key")
    else:
        add_result(results, "secret_key", "PASS", "secret_key 已自定义")

    if (settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD) in DEFAULT_ADMIN_CREDENTIALS:
        status = "FAIL" if auth_enabled else "WARN"
        add_result(results, "admin_credentials", status, "仍在使用默认 admin/admin")
    else:
        add_result(results, "admin_credentials", "PASS", "管理员账号密码已修改")

    if not settings.CORS_ALLOW_ORIGINS:
        add_result(results, "cors", "WARN", "cors_allow_origins 为空，浏览器前端将无法跨域访问")
    elif "*" in settings.CORS_ALLOW_ORIGINS:
        add_result(results, "cors", "WARN", "cors_allow_origins 含通配符 *")
    else:
        add_result(results, "cors", "PASS", ", ".join(settings.CORS_ALLOW_ORIGINS))

    legacy_state = await get_legacy_state()
    if legacy_state["legacy_app_config_count"] == 0 and not legacy_state["temp_cookies_exists"] and not legacy_state["downloads_zip_exists"]:
        add_result(results, "legacy_state", "PASS", "未检测到旧残留")
    else:
        details = []
        if legacy_state["legacy_app_config_count"]:
            details.append(f"旧版 app_config 键 {legacy_state['legacy_app_config_count']} 个")
        if legacy_state["temp_cookies_exists"]:
            details.append("存在 temp_cookies.txt")
        if legacy_state["downloads_zip_exists"]:
            details.append("存在 downloads.zip")
        add_result(results, "legacy_state", "WARN", "，".join(details))

    return results


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run preflight checks before real-site integration")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    results = await run_checks()
    has_fail = any(item["status"] == "FAIL" for item in results)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("ehentai_favorites_downloaderRERE Preflight")
        print("=" * 42)
        for item in results:
            print(f"[{item['status']:<4}] {item['name']}: {item['detail']}")

    return 1 if has_fail else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
