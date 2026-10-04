"""Build a native CLI or GUI distribution with PyInstaller."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from version import read_version
from validate_package import validate

def run(command, cwd=ROOT, env=None):
    subprocess.run([str(item) for item in command], cwd=cwd, env=env, check=True)

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def target():
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    arch = "arm64" if platform.machine().lower() in {"aarch64", "arm64"} else "x64"
    if system == "windows" and arch != "x64":
        raise RuntimeError("Windows arm64 is not a release target")
    return system, arch

def notices():
    entries = []
    for dist in importlib.metadata.distributions():
        for path in dist.files or []:
            if "license" in str(path).lower() or "copying" in str(path).lower():
                full = Path(dist.locate_file(path))
                if full.is_file() and full.stat().st_size < 500000:
                    entries.append(f"{dist.metadata['Name']} {dist.version}\n" + full.read_text(encoding="utf-8", errors="replace"))
    for path in (ROOT / "frontend/node_modules").glob("**/LICENSE*"):
        if path.is_file():
            entries.append(str(path.relative_to(ROOT / "frontend/node_modules")) + "\n" + path.read_text(encoding="utf-8", errors="replace"))
    return "\n\n".join(entries)

def build(flavor, output, skip_frontend=False):
    version = read_version()
    system, arch = target()
    name = "EFDRR" if flavor == "gui" else "efdrr-server"
    if not skip_frontend:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        run([npm, "ci"], ROOT / "frontend")
        run([npm, "run", "build"], ROOT / "frontend")
    run([sys.executable, ROOT / "scripts/icons.py", "--check"])
    if not (ROOT / "frontend/dist/index.html").exists():
        raise RuntimeError("Build frontend before packaging")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="efdrr-build-") as tmp:
        work = Path(tmp)
        env = dict(os.environ, EFDRR_DATA_ROOT=str(work / "isolated-data"), EFDRR_RESOURCE_ROOT=str(ROOT))
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--name", name, "--distpath", work / "dist", "--workpath", work / "work",
            "--specpath", work, "--paths", ROOT / "backend", "--paths", ROOT / "desktop",
            "--collect-submodules", "app", "--hidden-import", "sqlalchemy.dialects.sqlite.aiosqlite",
            "--hidden-import", "aiosqlite", "--hidden-import", "greenlet",
            "--hidden-import", "uvicorn.logging", "--hidden-import", "uvicorn.loops.asyncio",
            "--hidden-import", "uvicorn.protocols.http.h11_impl", "--hidden-import", "uvicorn.lifespan.on",
            "--copy-metadata", "apscheduler"]
        for path, destination in [("VERSION", "."), ("backend/config.yaml.example", "backend"),
            ("frontend/dist", "frontend/dist"), ("desktop/icon.ico", "desktop"),
            ("desktop/icon.png", "desktop"), ("desktop/icon.icns", "desktop")]:
            command.extend(["--add-data", str(ROOT / path) + ":" + destination])
        if system == "windows":
            command.extend(["--icon", ROOT / "desktop/icon.ico"])
        if flavor == "gui":
            command.append("--windowed")
            command.extend(["--collect-all", "webview"])
            if system == "macos":
                command.extend(["--icon", ROOT / "desktop/icon.icns",
                    "--osx-bundle-identifier", "io.github.WenHe233.EFDRR"])
            elif system == "linux":
                command.extend(["--hidden-import", "PySide6.QtWebEngineWidgets",
                    "--hidden-import", "PySide6.QtWebChannel", "--exclude-module", "PyQt5",
                    "--exclude-module", "PyQt6", "--exclude-module", "PySide2"])
        else:
            for module in ("webview", "pystray", "PySide6", "PyQt5", "PyQt6", "qtpy", "tkinter"):
                command.extend(["--exclude-module", module])
        command.append(ROOT / "desktop" / ("launcher.py" if flavor == "gui" else "server.py"))
        run(command, env=env)
        package = work / "package" / "EFDRR"
        package.mkdir(parents=True)
        if system == "macos" and flavor == "gui":
            shutil.copytree(work / "dist/EFDRR.app", package / "EFDRR.app", symlinks=True)
            executable = "EFDRR.app/Contents/MacOS/EFDRR"
            resources = "EFDRR.app/Contents/Resources"
            (package / "start.command").write_text('#!/bin/sh\nROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$ROOT/EFDRR.app/Contents/MacOS/EFDRR" --data-root "$ROOT" "$@"\n')
            (package / "start.command").chmod(0o755)
        else:
            shutil.copytree(work / "dist" / name, package, dirs_exist_ok=True, symlinks=True)
            executable = name + (".exe" if system == "windows" else "")
            resources = "_internal"
        if system == "linux" and flavor == "gui":
            shutil.copy2(ROOT / "desktop/icon.png", package / "icon.png")
            (package / "install-desktop-entry.sh").write_text('#!/bin/sh\nset -eu\nROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nDEST="$HOME/.local/share/applications"\nmkdir -p "$DEST"\ncat > "$DEST/efdrr.desktop" <<EOF\n[Desktop Entry]\nType=Application\nName=EFDRR\nExec="$ROOT/EFDRR"\nIcon=$ROOT/icon.png\nTerminal=false\nStartupWMClass=EFDRR\nCategories=Network;\nEOF\n', encoding="utf-8")
            (package / "install-desktop-entry.sh").chmod(0o755)
        shutil.copy2(ROOT / "desktop/README.txt", package / "README.txt")
        shutil.copy2(ROOT / "VERSION", package / "VERSION")
        (package / "THIRD_PARTY_NOTICES.txt").write_text(notices(), encoding="utf-8")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        metadata = dict(version=version, commit=revision, python=platform.python_version(), flavor=flavor,
            platform=system, arch=arch, executable=executable, resources=resources,
            icons={ext: sha256(ROOT / f"desktop/icon.{ext}") for ext in ("ico", "png", "icns")})
        (package / "BUILD-INFO.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        basename = f"EFDRR-{version}-{flavor}-{system}-{arch}"
        path = output / (basename + (".zip" if system == "windows" else ".tar.gz"))
        if system == "windows":
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for item in sorted(package.rglob("*")):
                    if item.is_file():
                        archive.write(item, item.relative_to(package.parent).as_posix())
        else:
            with tarfile.open(path, "w:gz") as archive:
                archive.add(package, arcname="EFDRR")
        validate(path)
        print(path)
        return path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--flavor", choices=["cli", "gui"], required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--skip-frontend", action="store_true")
    args = parser.parse_args()
    build(args.flavor, args.output.resolve(), args.skip_frontend)
