"""Run a freshly extracted package against isolated data, never user accounts."""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

import httpx
import yaml
from validate_package import validate

def wait_ready(url, process=None, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process and process.poll() is not None:
            raise RuntimeError(f"Process exited before ready: {process.returncode}")
        try:
            with httpx.Client(timeout=2) as client:
                response = client.get(url + "/api/v1/health")
                if response.status_code == 200 and response.json()["status"] == "ok":
                    return response.json()
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(.3)
    raise RuntimeError("Health check timed out")

def verify_http(url, data_root, expected_version, expected_limit=None):
    config = yaml.safe_load((Path(data_root) / "config.yaml").read_text(encoding="utf-8"))
    with httpx.Client(base_url=url, timeout=10) as client:
        assert client.get("/api/v1/health").json()["version"] == expected_version
        for route in ("/", "/login", "/galleries", "/settings"):
            response = client.get(route)
            assert response.status_code == 200 and 'id="root"' in response.text, route
        assert "<svg" in client.get("/efdrr-icon.svg").text
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/api/v1/missing").status_code == 404
        assert client.get("/api/v1/settings").status_code == 401
        token = client.post("/api/v1/auth/login", json={
            "username": config["security"]["admin_username"],
            "password": config["security"]["admin_password"]}).json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        before = client.get("/api/v1/settings").json()
        if expected_limit is not None:
            assert before["max_concurrent_downloads"] == expected_limit
        assert client.post("/api/v1/settings", json={"max_concurrent_downloads": 2}).status_code == 200
        assert client.get("/api/v1/settings").json()["max_concurrent_downloads"] == 2
        with client.stream("GET", "/api/v1/events/downloads") as response:
            assert response.status_code == 200
            assert next(line for line in response.iter_lines() if line).startswith("event: snapshot")
    assert yaml.safe_load((Path(data_root) / "config.yaml").read_text(encoding="utf-8"))["download"]["max_concurrent_downloads"] == 2

def stop(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=40)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise RuntimeError("Server did not shut down gracefully")

def smoke(path, no_tray=False):
    info = validate(path)
    env = {k:v for k,v in os.environ.items() if k not in {"EFDRR_DATA_ROOT", "EFDRR_RESOURCE_ROOT", "PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONUTF8"] = "1"
    with tempfile.TemporaryDirectory(prefix="efdrr-smoke-") as temp:
        work = Path(temp)
        extracted = work / "程序 with spaces"
        extracted.mkdir()
        if str(path).endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                archive.extractall(extracted)
        else:
            with tarfile.open(path) as archive:
                archive.extractall(extracted, filter="data")
        root = extracted / "EFDRR"
        exe = root / info["executable"]
        data = work / "测试数据 with spaces"
        data.mkdir()
        command = [str(exe)]
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        log = work / "process.log"
        try:
            if info["flavor"] == "gui":
                report = work / "gui.json"
                with log.open("wb") as stream:
                    process = subprocess.Popen(command + ["--data-root", str(data), "--smoke-test", str(report)] + (["--no-tray"] if no_tray else []),
                        env=env, cwd=work, stdout=stream, stderr=stream, creationflags=creationflags)
                    try:
                        result = process.wait(timeout=180)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise RuntimeError("GUI smoke timed out")
                if result != 0 or not report.exists():
                    raise RuntimeError("GUI failed: " + log.read_text(encoding="utf-8", errors="replace"))
                result = json.loads(report.read_text(encoding="utf-8"))
                assert result["success"] and result["brand"] and result["login"], result
                if no_tray:
                    assert not result["tray"]
                elif sys.platform in {"win32", "darwin"} or os.environ.get("EFDRR_REQUIRE_TRAY") == "1":
                    assert result["tray"]
            else:
                version = subprocess.check_output(command + ["--version"], env=env, text=True).strip()
                assert version == info["version"]
                assert "--data-root" in subprocess.check_output(command + ["--help"], env=env, text=True)
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                url = f"http://127.0.0.1:{port}"
                for iteration in range(2):
                    with log.open("ab") as stream:
                        process = subprocess.Popen(command + ["--port", str(port), "--data-root", str(data)], env=env, cwd=work,
                            stdout=stream, stderr=stream, creationflags=creationflags)
                        try:
                            wait_ready(url, process)
                            verify_http(url, data, info["version"], expected_limit=2 if iteration else None)
                            duplicate = subprocess.run(command + ["--port", str(port+1 if port < 65535 else port-1), "--data-root", str(data)],
                                env=env, capture_output=True, timeout=30)
                            assert duplicate.returncode != 0
                        finally:
                            stop(process)
                assert "Application shutdown complete" in log.read_text(encoding="utf-8", errors="replace")
                result = dict(success=True, health=True, auth=True, routes=True, sse=True, persistence=True, lock=True, graceful_shutdown=True)
            result["package"] = Path(path).name
            return result
        except Exception:
            if log.exists():
                print(log.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
            crash = data / "data/desktop-crash.log"
            if crash.exists():
                print(crash.read_text(encoding="utf-8"), file=sys.stderr)
            raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--no-tray", action="store_true")
    args = parser.parse_args()
    results = [smoke(p, args.no_tray) for p in sorted(args.directory.iterdir()) if p.name.endswith((".zip", ".tar.gz"))]
    if not results:
        raise SystemExit("No package found")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=True))
