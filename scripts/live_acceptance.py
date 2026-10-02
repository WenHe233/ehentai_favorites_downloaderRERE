"""Explicit, isolated live tests. Cookies are never written to reports or CI."""
import argparse
import asyncio
import json
import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def read_cookies(path):
    raw = path.read_text(encoding="utf-8-sig")
    cookies = {key: value.strip().strip('"').strip("'") for key, value in re.findall(r"(ipb_member_id|ipb_pass_hash|igneous)\s*=\s*([^;\r\n]+)", raw)}
    if not cookies.get("ipb_member_id") or not cookies.get("ipb_pass_hash"):
        raise ValueError("Missing account cookies in local .env")
    return cookies


class Budget:
    def __init__(self, path, maximum=10000):
        self.path = path
        self.maximum = maximum
        self.state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"reserved_gp": 0, "purchases": []}

    async def authorize(self, *, gid, quality, html, form):
        from bs4 import BeautifulSoup
        from app.core.archiver import ArchiveAuthorizationError
        block = form.parent.get_text(" ", strip=True)
        quote = re.search(r"Download Cost:\s*(Free!?|([\d,]+)\s*(GP|Credits))", block, re.I)
        if not quote or (quote.group(3) and quote.group(3).lower() != "gp"):
            raise ArchiveAuthorizationError("归档报价未知或使用 Credits，已停止测试请求")
        amount = int(quote.group(2).replace(",", "")) if quote.group(2) else 0
        text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
        available = re.search(r"([\d,]+)\s+GP\b", text)
        if amount and (not available or int(available.group(1).replace(",", "")) < amount):
            raise ArchiveAuthorizationError("无法确认 GP 足额，已停止测试请求")
        if self.state["reserved_gp"] + amount > self.maximum:
            raise ArchiveAuthorizationError("真实联调将超过 GP 总额上限")
        self.state["reserved_gp"] += amount
        self.state["purchases"].append({"gid": gid, "quality": quality, "quoted_gp": amount})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")


async def run(args):
    os.environ["EFDRR_DATA_ROOT"] = str(args.work.resolve())
    from app.core.config import settings
    from app.core.client import eh_client
    from app.core.archiver import GalleryArchiver
    from app.db.database import init_models, SessionLocal, engine
    from app.db.models import Gallery
    from app.services.downloader import downloader
    from app.services.config_service import config_service
    from loguru import logger

    args.work.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(args.work / "acceptance.log", level="INFO")
    payload = settings.reload()
    payload["security"]["enable_auth"] = False
    settings._write_yaml(payload)
    settings.reload(force=True)
    settings.update_runtime_settings({**read_cookies(args.cookies), "eh_domain": args.domain, "auto_sync": False, "monitored_favcats": [], "telegram_bot_token": None,
        "telegram_notifications_enabled": False, "max_concurrent_downloads": 2, "max_retries": 1, "archive_quality": "original"})
    await init_models()
    budget = Budget(args.work.parent / "gp-ledger.json", args.max_gp)
    original_prepare = GalleryArchiver.prepare_and_poll
    async def guarded_prepare(*positional, **keywords):
        return await original_prepare(*positional, **keywords, before_purchase=budget.authorize)
    GalleryArchiver.prepare_and_poll = staticmethod(guarded_prepare)
    samples = json.loads(args.samples.read_text(encoding="utf-8"))
    report = {"results": [], "budget_limit_gp": args.max_gp, "success": False}
    report_path = args.work / "report.json"
    try:
        for sample in samples:
            if int(sample["filecount"]) > 50:
                raise ValueError("Live test sample exceeds 50 images")
            gid = sample["gid"]
            async with SessionLocal() as db:
                gallery = await db.get(Gallery, (gid, sample["token"]))
                if not gallery:
                    gallery = Gallery(gid=gid, token=sample["token"], title=sample["title"], title_jpn=sample.get("title_jpn"), filecount=int(sample["filecount"]), status="failed", error_msg="historical filename failure")
                    db.add(gallery)
                    await db.commit()
            for mode in ("archive", "native_crawl"):
                # The existing DB row stays in place while settings are corrected.
                settings.update_runtime_settings({"download_mode": mode, "output_template": "./downloads/" + mode + "/[{gid}] {title}.zip", "truncate_filenames": False})
                if len(sample["title"]) > 160:
                    failed = await downloader._download_gallery(gallery, mode)
                    if failed or "过长" not in (gallery.error_msg or ""):
                        raise AssertionError("Expected the old long filename configuration to fail before download")
                settings.update_runtime_settings({"truncate_filenames": True, "filename_max_length": 80})
                gallery.error_msg = None
                async with SessionLocal() as db:
                    existing = await db.get(Gallery, (gid, sample["token"]))
                    existing.status = "pending"
                    existing.error_msg = None
                    await db.commit()
                await downloader._run_sequential_gallery(gallery)
                async with SessionLocal() as db:
                    stored = await db.get(Gallery, (gid, sample["token"]))
                    success = stored.status == "completed"
                    images = 0
                    if success:
                        with zipfile.ZipFile(stored.download_path) as archive:
                            assert archive.testzip() is None
                            images = len([name for name in archive.namelist() if not name.endswith("/")])
                        assert images >= int(sample["filecount"])
                    result = {"gid": gid, "mode": mode, "title_characters": len(sample["title"]), "expected_images": int(sample["filecount"]), "archived_images": images, "success": success, "error": stored.error_msg if not success else None}
                    report["results"].append(result)
                    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps(result, ensure_ascii=True), flush=True)
                    if not success:
                        raise RuntimeError("Live download failed; inspect local acceptance log")
        report["success"] = True
    finally:
        report["reserved_gp"] = budget.state["reserved_gp"]
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        await eh_client.close()
        await engine.dispose()
        # Test configuration is private and stays under the ignored dev directory.
        GalleryArchiver.prepare_and_poll = original_prepare


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookies", type=Path, default=ROOT / ".env")
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=ROOT / "dev/live/run")
    parser.add_argument("--max-gp", type=int, default=10000)
    parser.add_argument("--domain", choices=["e-hentai.org", "exhentai.org"], default="e-hentai.org")
    args = parser.parse_args()
    if args.max_gp < 0 or args.max_gp > 10000:
        parser.error("This acceptance run is authorized for at most 10000 GP")
    asyncio.run(run(args))
