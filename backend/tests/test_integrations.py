import asyncio
import io
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from bs4 import BeautifulSoup
from PIL import Image

from app.core.config import settings
from app.core.http_cookies import site_cookies
from app.db.database import SessionLocal
from app.db.models import Gallery


def test_account_cookies_do_not_leak_to_image_hosts():
    client=httpx.Client(cookies=site_cookies({'ipb_member_id':'test','igneous':'test-igneous'}))
    assert 'ipb_member_id' in client.build_request('GET','https://e-hentai.org/favorites.php').headers['cookie']
    assert 'igneous' not in client.build_request('GET','https://e-hentai.org/').headers['cookie']
    assert 'cookie' not in client.build_request('GET','https://images.example.test/image.jpg').headers


async def test_cookie_reload_does_not_interrupt_inflight_request(monkeypatch):
    from app.core.client import EHClient
    started=asyncio.Event();finish=asyncio.Event()
    async def handler(request):
        started.set();await finish.wait();return httpx.Response(200,text='ok')
    service=EHClient()
    old=httpx.AsyncClient(transport=httpx.MockTransport(handler));service._client=old
    request=asyncio.create_task(service._request('GET','https://example.test'))
    await started.wait();await service.close();assert not old.is_closed
    finish.set();assert (await request).text=='ok';assert old.is_closed


async def test_native_resume_excludes_incomplete_images(tmp_path):
    from app.core.native_crawler import NativeCrawler
    Image.new('RGB',(2,2),'red').save(tmp_path/'0001.png')
    (tmp_path/'0002.jpg').write_bytes(b'incomplete')
    (tmp_path/'0003.png.part').write_bytes(b'partial')
    assert list(NativeCrawler._scan_downloaded_files(tmp_path,3))==[1]


async def test_native_packaging_failure_preserves_previous_archive_and_images(tmp_path):
    from app.core.native_crawler import NativeCrawler
    import zipfile
    image = tmp_path / '0001.png'
    Image.new('RGB', (2, 2), 'red').save(image)
    destination = tmp_path / 'gallery.zip'
    with zipfile.ZipFile(destination, 'w') as archive:
        archive.writestr('previous.txt', 'previous version')
    previous = destination.read_bytes()
    async def interrupt(**kwargs):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await NativeCrawler._write_zip(destination, {1: image}, interrupt,
            detail_prefix='test', percent_start=90, percent_span=10)
    assert destination.read_bytes() == previous
    assert image.exists()
    assert not destination.with_name('gallery.zip.tmpdownload').exists()
    await NativeCrawler._write_zip(destination, {1: image}, None,
        detail_prefix='test', percent_start=90, percent_span=10)
    with zipfile.ZipFile(destination) as archive:
        assert archive.namelist() == ['0001.png']
        assert archive.testzip() is None


def test_cross_volume_archive_copy_failure_preserves_cache_and_destination(tmp_path, monkeypatch):
    import errno
    import zipfile
    from app.core.archive_cache import ArchiveCache
    import app.core.archive_cache as module
    cache = ArchiveCache(tmp_path / 'source.download', 1, 'sample', 'original')
    with zipfile.ZipFile(cache.path, 'w') as archive:
        archive.writestr('001.txt', 'sample')
    cache.mark_complete()
    destination = tmp_path / 'existing.zip'
    destination.write_bytes(b'previous archive')
    real_replace = module.os.replace
    def replace(source, target):
        if source == cache.path:
            raise OSError(errno.EXDEV, 'cross-device')
        return real_replace(source, target)
    monkeypatch.setattr(module.os, 'replace', replace)
    copy = module.shutil.copyfile
    def disk_full(source, target):
        target.write_bytes(b'incomplete')
        raise OSError(errno.ENOSPC, 'disk full')
    monkeypatch.setattr(module.shutil, 'copyfile', disk_full)
    with pytest.raises(OSError):
        cache.publish(destination)
    assert cache.valid()
    assert destination.read_bytes() == b'previous archive'
    assert not destination.with_name('existing.zip.tmpdownload').exists()
    monkeypatch.setattr(module.shutil, 'copyfile', copy)
    cache.publish(destination)
    with zipfile.ZipFile(destination) as archive:
        assert archive.read('001.txt') == b'sample'
    assert not cache.path.exists()


async def test_cancel_before_task_starts_does_not_leave_reserved_slot():
    from app.services.downloader import downloader
    task=asyncio.create_task(asyncio.sleep(100))
    downloader._active_downloads[123]=task
    task.add_done_callback(lambda done:downloader._forget_task(123,done))
    assert await downloader.cancel_and_wait(123)
    await asyncio.sleep(0)
    assert 123 not in downloader._active_downloads


async def test_startup_restores_interrupted_native_task():
    from app.services.startup_recovery import startup_recovery_service
    async with SessionLocal() as db:
        db.add(Gallery(gid=1,token='sample',title='sample',status='downloading',download_mode='native_crawl'))
        await db.commit()
    summary=await startup_recovery_service.recover_interrupted_downloads()
    assert summary.recovered_total==1
    async with SessionLocal() as db:assert (await db.get(Gallery,(1,'sample'))).status=='pending'


async def test_stored_native_failure_retries_new_path_without_refetching_images(monkeypatch):
    from app.core.native_crawler import NativeCrawler, ImageDownloadResult
    from app.core.client import eh_client
    from app.services.downloader import downloader
    from app.main import app
    from pathlib import Path
    settings.update_runtime_settings({'download_mode':'native_crawl','conflict_strategy':'overwrite'})
    gallery = Gallery(gid=77,token='sample',title='長い.标题' * 70,status='pending',filecount=1)
    async with SessionLocal() as db:
        db.add(gallery)
        await db.commit()
    monkeypatch.setattr(eh_client, 'get_html', AsyncMock(return_value='<div id="gdt"><a href="https://e-hentai.org/s/a/77-1">1</a></div>'))
    async def image_download(url, directory, index, **kwargs):
        path = directory / '0001.png'
        Image.new('RGB',(2,2),'red').save(path)
        return ImageDownloadResult(path,quality='native')
    fetch = AsyncMock(side_effect=image_download)
    monkeypatch.setattr(NativeCrawler, '_download_page_image', fetch)
    package = NativeCrawler._write_zip
    monkeypatch.setattr(NativeCrawler, '_write_zip', AsyncMock(side_effect=PermissionError('output locked')))
    await downloader._process_queue_concurrent()
    await asyncio.gather(*list(downloader._active_downloads.values()))
    async with SessionLocal() as db:
        assert (await db.get(Gallery,(77,'sample'))).status == 'failed'
    assert NativeCrawler.describe_resume_artifacts(77)['downloaded_files'] == 1
    settings.update_runtime_settings({'filename_max_length':80,'output_template':'./retry/{gid}-{title}-{quality}.zip'})
    monkeypatch.setattr(NativeCrawler, '_write_zip', package)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.post('/api/v1/galleries/77/reset')).status_code == 200
    await downloader._process_queue_concurrent()
    await asyncio.gather(*list(downloader._active_downloads.values()))
    async with SessionLocal() as db:
        result = await db.get(Gallery,(77,'sample'))
        assert result.status == 'completed'
        assert result.error_msg is None
        assert result.title == gallery.title
        assert result.resolved_quality == 'native'
        assert Path(result.download_path).parent.name == 'retry'
        assert len(Path(result.download_path).name) <= 80
        assert result.download_mode == 'native_crawl'
        assert 'output locked' in str(result.download_logs)
    fetch.assert_awaited_once()


async def test_telegram_buffer_survives_restart_without_real_messages(monkeypatch):
    from app.services.notification_service import NotificationService, NotificationEvent
    service=NotificationService();runtime=await service._get_runtime_settings()
    runtime=replace(runtime,enabled=True,token='test',recipients=[1],batch_window_seconds=60)
    event=NotificationEvent(event_id='sample',kind='download_completed',created_at=datetime.now(timezone.utc),gid=1,title='test')
    await service._dispatch_event(event,runtime=runtime);await service._cancel_flush_task()
    restored=NotificationService();send=AsyncMock(return_value=[]);monkeypatch.setattr(restored,'_send_message',send)
    await restored._flush_pending(runtime)
    send.assert_awaited_once();assert not (await restored._read_buffer_state()).events


async def test_telegram_retry_only_targets_failed_recipients_after_restart(monkeypatch):
    from app.services.notification_service import NotificationService, NotificationEvent
    service = NotificationService()
    runtime = replace(await service._get_runtime_settings(), enabled=True, token='test', recipients=[1,2], batch_window_seconds=0)
    event = NotificationEvent(event_id='sample', kind='download_completed', created_at=datetime.now(timezone.utc), gid=1, title='test')
    send = AsyncMock(return_value=[2])
    monkeypatch.setattr(service, '_send_message', send)
    await service._dispatch_event(event, runtime=runtime)
    await service._cancel_flush_task()
    restored = NotificationService()
    retry = AsyncMock(return_value=[])
    monkeypatch.setattr(restored, '_send_message', retry)
    await restored._flush_pending(runtime)
    assert retry.await_args.args[1].recipients == [2]
    assert not (await restored._read_buffer_state()).events


async def test_free_and_paid_archive_budget_is_cumulative(tmp_path):
    from scripts.live_acceptance import Budget
    from app.core.archiver import ArchiveAuthorizationError
    budget=Budget(tmp_path/'ledger.json')
    async def authorize(cost):
        soup=BeautifulSoup('<div>Download Cost: '+cost+'<form></form></div>','lxml')
        await budget.authorize(gid=1,quality='original',html='20,000 GP [ balance ]',form=soup.form)
    await authorize('Free!');await authorize('6,000 GP')
    with pytest.raises(ArchiveAuthorizationError):await authorize('5,000 GP')
    with pytest.raises(ArchiveAuthorizationError):await authorize('100 Credits')
    with pytest.raises(ArchiveAuthorizationError):await authorize('Unknown')
    assert Budget(tmp_path/'ledger.json').state['reserved_gp']==6000
