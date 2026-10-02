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


async def test_telegram_buffer_survives_restart_without_real_messages(monkeypatch):
    from app.services.notification_service import NotificationService, NotificationEvent
    service=NotificationService();runtime=await service._get_runtime_settings()
    runtime=replace(runtime,enabled=True,token='test',recipients=[1],batch_window_seconds=60)
    event=NotificationEvent(event_id='sample',kind='download_completed',created_at=datetime.now(timezone.utc),gid=1,title='test')
    await service._dispatch_event(event,runtime=runtime);await service._cancel_flush_task()
    restored=NotificationService();send=AsyncMock(return_value=[]);monkeypatch.setattr(restored,'_send_message',send)
    await restored._flush_pending(runtime)
    send.assert_awaited_once();assert not (await restored._read_buffer_state()).events


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
