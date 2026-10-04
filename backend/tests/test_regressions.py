import asyncio
import io
import json
import zipfile
from copy import deepcopy
from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.archive_cache import ArchiveCache
from app.core.archiver import ArchiveDownloadResult
from app.db.database import SessionLocal
from app.db.models import Gallery, DownloadStatus


async def test_invalid_configuration_is_atomic():
    before = settings.CONFIG_PATH.read_bytes()
    old = settings.MAX_CONCURRENT_DOWNLOADS
    with pytest.raises(ValueError):
        settings.update_runtime_settings({"max_concurrent_downloads": None})
    assert settings.CONFIG_PATH.read_bytes() == before
    assert settings.MAX_CONCURRENT_DOWNLOADS == old


async def test_progress_preserves_concurrent_retry_state():
    from app.services.sync_state import read_sync_state, upsert_failed_gallery, write_sync_progress
    stale = await read_sync_state()
    gallery = Gallery(gid=123, token="sample", title="sample", favcat=7)
    await upsert_failed_gallery(gallery)
    stale["last_favorited"]["1"] = "2026-01-01 00:00"
    await write_sync_progress(stale)
    state = await read_sync_state()
    assert state["failed"]["123"]["favcat"] == 7
    assert state["last_favorited"]["1"] == "2026-01-01 00:00"


def test_new_category_not_cut_off_by_other_categories():
    from app.services.updater import UpdaterService
    assert UpdaterService._effective_since({"last_run_ts": "2026-01-01 00:00", "last_favorited": {}}, 7, None) == datetime.min


async def test_native_crawler_includes_last_pagination_page(monkeypatch):
    from app.core.native_crawler import NativeCrawler
    from app.core.client import eh_client
    html = '<div id="gdt"><a href="https://e-hentai.org/s/a/1-1">1</a></div><div class="ptt"><a href="?p=1">2</a></div>'
    fetch = AsyncMock(return_value='<div id="gdt"><a href="https://e-hentai.org/s/b/1-2">2</a></div>')
    monkeypatch.setattr(eh_client, "get_html", fetch)
    urls = await NativeCrawler._get_page_urls("https://e-hentai.org/g/1/token/", BeautifulSoup(html, "lxml"))
    assert len(urls) == 2
    fetch.assert_awaited_once()


async def test_manual_entry_does_not_restart_active_download(monkeypatch):
    import app.services.manual_queue as queue
    async with SessionLocal() as db:
        db.add(Gallery(gid=42, token="old", title="running", status="downloading"))
        await db.commit()
        monkeypatch.setattr(queue, "_fetch_gallery_metadata", AsyncMock(return_value=(42, "new", {"title": "updated"}, False)))
        result = await queue.queue_manual_gallery("https://e-hentai.org/g/42/old/", db)
        assert result.status == "Exists"
        assert (await db.get(Gallery, (42, "old"))).status == "downloading"


async def test_long_title_failed_record_retries_with_new_settings(monkeypatch):
    from app.services.downloader import downloader
    from app.core.archiver import GalleryArchiver
    title = "A." + "長い中文标题" * 80
    async with SessionLocal() as db:
        gallery = Gallery(gid=99, token="sample", title=title, status="failed", error_msg="File name too long", retry_count=1)
        db.add(gallery)
        await db.commit()
    settings.update_runtime_settings({"truncate_filenames": False})
    prepare = AsyncMock(return_value=("https://example.test/archive.zip", 20))
    monkeypatch.setattr(GalleryArchiver, "prepare_and_poll", prepare)
    async def download(url, destination, **kwargs):
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("001.txt", "fixture")
        return ArchiveDownloadResult(success=True)
    monkeypatch.setattr(GalleryArchiver, "download_file", download)
    assert not await downloader._download_gallery(gallery, "archive")
    prepare.assert_not_awaited()
    settings.update_runtime_settings({"truncate_filenames": True, "filename_max_length": 80})
    assert await downloader._download_gallery(gallery, "archive")
    assert gallery.title == title
    assert len(__import__('pathlib').Path(gallery.download_path).name) <= 80
    prepare.assert_awaited_once()


async def test_verified_archive_reused_after_destination_error(monkeypatch):
    from app.services.downloader import downloader
    from app.core.archiver import GalleryArchiver
    gallery = Gallery(gid=101, token="sample", title="long." + "中" * 200)
    root = settings.DATA_DIR / "archive_temp"
    root.mkdir(parents=True)
    cache = ArchiveCache(root / "101.download", 101, "sample", "original")
    with zipfile.ZipFile(cache.path, "w") as archive:
        archive.writestr("001.txt", "fixture")
    cache.mark_complete()
    prepare = AsyncMock(side_effect=AssertionError("paid request must not be repeated"))
    monkeypatch.setattr(GalleryArchiver, "prepare_and_poll", prepare)
    real_publish = ArchiveCache.publish
    monkeypatch.setattr(ArchiveCache, "publish", lambda *args: (_ for _ in ()).throw(PermissionError("locked")))
    assert not await downloader._download_gallery(gallery, "archive")
    assert cache.valid()
    monkeypatch.setattr(ArchiveCache, "publish", real_publish)
    settings.update_runtime_settings({"filename_max_length": 80, "output_template": "./downloads/{gid}-{title}.zip"})
    assert await downloader._download_gallery(gallery, "archive")
    prepare.assert_not_awaited()


async def test_health_and_configuration_errors():
    from app.main import app
    app.state.ready = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
        from app.core.runtime import VERSION
        assert response.json() == {"status": "ok", "version": VERSION}
        response = await client.post("/api/v1/settings", json={"max_concurrent_downloads": -1})
        assert response.status_code == 400


def test_unicode_admin_credentials():
    from app.core.security import authenticate_admin
    payload = deepcopy(settings._raw_config)
    payload["security"].update(enable_auth=True, admin_username="管理员", admin_password="密码测试")
    settings._write_yaml(payload)
    settings.reload(force=True)
    assert authenticate_admin("管理员", "密码测试")
    assert authenticate_admin("管理员", "错误") is None


@pytest.mark.parametrize("path", ["api/v1/missing", "api\\v1\\missing", "assets/missing", "assets\\missing"])
async def test_spa_never_serves_api_or_assets_as_html(tmp_path, path):
    from app.core.spa import SPAStaticFiles
    from starlette.exceptions import HTTPException
    (tmp_path / "index.html").write_text("<html>shell</html>")
    static = SPAStaticFiles(directory=tmp_path, html=True)
    with pytest.raises(HTTPException) as error:
        await static.get_response(path, {"method": "GET"})
    assert error.value.status_code == 404
