import os
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"desktop"))
from desktop_runtime import InstanceLock, configure, portable_root, resource_root
from server import port_number

def test_data_directory_precedence_and_unicode(tmp_path,monkeypatch):
    explicit=tmp_path/"中文 with spaces"
    monkeypatch.setenv("EFDRR_DATA_ROOT",str(tmp_path/"environment"))
    resources,data=configure(explicit)
    assert data==explicit.resolve()
    assert (data/"data").is_dir()
    monkeypatch.setenv("EFDRR_DATA_ROOT",str(tmp_path/"environment"))
    assert configure()[1]==(tmp_path/"environment").resolve()

def test_lock_excludes_another_process_and_releases(tmp_path):
    command=[sys.executable,"-c",
        "import sys;sys.path.insert(0,sys.argv[1]);from desktop_runtime import InstanceLock;lock=InstanceLock(sys.argv[2]);lock.__enter__()",
        str(ROOT/"desktop"),str(tmp_path)]
    with InstanceLock(tmp_path):
        assert subprocess.run(command,capture_output=True).returncode!=0
    assert subprocess.run(command,capture_output=True).returncode==0

def test_mac_bundle_data_outside_app(tmp_path,monkeypatch):
    monkeypatch.setattr(sys,"frozen",True,raising=False)
    monkeypatch.setattr(sys,"executable",str(tmp_path/"EFDRR.app/Contents/MacOS/EFDRR"))
    assert portable_root()==tmp_path

def test_frozen_resources_independent_from_data(tmp_path,monkeypatch):
    monkeypatch.delenv("EFDRR_RESOURCE_ROOT",raising=False)
    monkeypatch.setattr(sys,"_MEIPASS",str(tmp_path/"resources"),raising=False)
    assert resource_root()==(tmp_path/"resources").resolve()

@pytest.mark.parametrize("value",["0","65536","-1"])
def test_invalid_port(value):
    with pytest.raises(Exception):
        port_number(value)

def test_help_and_version_do_not_create_data(tmp_path):
    env=dict(os.environ,EFDRR_DATA_ROOT=str(tmp_path/"unused"),EFDRR_RESOURCE_ROOT=str(ROOT),PYTHONUTF8="1")
    for option in ("--help","--version"):
        completed=subprocess.run([sys.executable,str(ROOT/"desktop/server.py"),option],env=env,capture_output=True)
        assert completed.returncode==0
    assert not (tmp_path/"unused").exists()

def test_missing_brand_icon_is_reported(tmp_path):
    from tray import TrayManager
    with pytest.raises(FileNotFoundError):
        TrayManager(None,None,tmp_path,tmp_path,tmp_path/"absent.png")

def test_no_tray_closes_without_hiding(tmp_path):
    from tray import TrayManager
    icon=tmp_path/"icon.png"
    icon.write_bytes(b"fixture")
    tray=TrayManager(None,None,tmp_path,tmp_path,icon,disabled=True)
    assert tray.handle_window_closing() is True
