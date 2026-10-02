"""Separate read-only application resources from user-owned portable data."""
import os
from pathlib import Path

RESOURCE_ROOT = Path(os.environ.get("EFDRR_RESOURCE_ROOT", Path(__file__).resolve().parents[3])).resolve()
BASE_DIR = Path(os.environ.get("EFDRR_DATA_ROOT", Path(__file__).resolve().parents[2])).resolve()
VERSION = (RESOURCE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
FRONTEND_DIST_DIR = RESOURCE_ROOT / "frontend" / "dist"
