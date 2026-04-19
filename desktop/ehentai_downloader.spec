# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for EHentai Favorites Downloader desktop GUI.

Build with:
    pyinstaller desktop/ehentai_downloader.spec
"""

import os
import sys
from pathlib import Path

spec_dir = SPECPATH  # noqa: F821  (SPECPATH is injected by PyInstaller; it is the directory containing this .spec file)
project_root = os.path.dirname(spec_dir)

a = Analysis(
    [os.path.join(spec_dir, 'launcher.py')],
    pathex=[os.path.join(project_root, 'backend')],
    binaries=[],
    datas=[
        # Pre-built React frontend
        (os.path.join(project_root, 'frontend', 'dist'), 'frontend_dist'),
        # Default config template
        (os.path.join(project_root, 'backend', 'config.yaml.example'), '.'),
        # Application icon (for tray)
        (os.path.join(spec_dir, 'icon.ico'), '.'),
        # Tray module (loaded at runtime by launcher)
        (os.path.join(spec_dir, 'tray.py'), '.'),
    ],
    hiddenimports=[
        # --- uvicorn internals ---
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # --- async DB ---
        'aiosqlite',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.sqlite.aiosqlite',
        # --- auth / crypto ---
        'passlib.handlers.bcrypt',
        'jose',
        'jose.jwt',
        'jose.jws',
        'jose.constants',
        'jose.utils',
        'jose.backends',
        'jose.backends.native_backend',
        # --- multipart (FastAPI file upload) ---
        'multipart',
        'multipart.multipart',
        # --- anyio ---
        'anyio._backends',
        'anyio._backends._asyncio',
        # --- httpx / httpcore ---
        'httpx',
        'httpcore',
        'httpcore._async',
        'httpcore._sync',
        'h11',
        # --- pydantic ---
        'pydantic',
        'pydantic_core',
        # --- apscheduler ---
        'apscheduler.triggers.interval',
        'apscheduler.schedulers.asyncio',
        # --- aiogram (Telegram bot) ---
        'aiogram',
        # --- other ---
        'aiofiles',
        'tenacity',
        'loguru',
        'lxml',
        'bs4',
        'yaml',
        'pystray',
        'PIL',
        'webview',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        # Anaconda ships these but we don't need them; they can cause import errors during analysis.
        'matplotlib',
        'matplotlib_inline',
        'numpy',
        'scipy',
        'pandas',
        'IPython',
        'notebook',
        'jupyter',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ehentai_downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No console window on Windows
    icon=os.path.join(spec_dir, 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ehentai_downloader',
)
