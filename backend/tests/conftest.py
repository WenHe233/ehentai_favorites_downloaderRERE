import os
import tempfile
from copy import deepcopy

import pytest_asyncio

_bootstrap = tempfile.TemporaryDirectory(prefix="efdrr-tests-")
os.environ["EFDRR_DATA_ROOT"] = _bootstrap.name


@pytest_asyncio.fixture(autouse=True)
async def isolated_state(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.core.config import settings, DEFAULT_CONFIG
    from app.db import database
    from app.db.models import Gallery  # register models
    from app.services.downloader import downloader
    from app.services.realtime import realtime_hub
    payload = deepcopy(DEFAULT_CONFIG)
    payload["security"].update(enable_auth=False, secret_key="test-key-not-a-production-secret")
    payload["sync"].update(auto_sync=False, monitored_favcats=[])
    settings.BASE_DIR = tmp_path
    settings.CONFIG_PATH = tmp_path / "config.yaml"
    settings._write_yaml(payload)
    settings.reload(force=True)
    await database.engine.dispose()
    database.engine = create_async_engine(settings.DATABASE_URL)
    database.SessionLocal.configure(bind=database.engine)
    await database.init_models()
    downloader._active_downloads.clear()
    downloader._cancelled_gids.clear()
    downloader._active_count = 0
    downloader._semaphore = None
    downloader.is_running = False
    await realtime_hub.clear_all()
    yield
    await downloader.stop()
    from app.services.notification_service import notification_service
    await notification_service._cancel_flush_task()
    from app.core.client import eh_client
    await eh_client.close()
    await database.engine.dispose()
