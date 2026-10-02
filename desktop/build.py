"""Build a Windows portable app on Linux without running Windows binaries."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from version import read_version


def run(command, cwd=ROOT):
    subprocess.run([str(item) for item in command], cwd=cwd, check=True)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or sha256(target) != expected:
        temporary = target.with_suffix(".downloading")
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        if sha256(temporary) != expected:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("Download checksum mismatch: " + target.name)
        temporary.replace(target)
    return target


def split_lock(text):
    records, current = [], []
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            if current:
                records.append("\n".join(current))
            current = [line]
        elif current and line.lstrip().startswith("--hash"):
            current.append(line)
    if current:
        records.append("\n".join(current))
    return records


def frontend_licenses():
    result = []
    for manifest in (ROOT / "frontend/node_modules").glob("**/package.json"):
        if "node_modules" not in manifest.parts:
            continue
        try:
            package = json.loads(manifest.read_text(encoding="utf-8"))
            notices = list(manifest.parent.glob("LICENSE*")) + list(manifest.parent.glob("LICENCE*"))
            for notice in notices:
                if notice.is_file():
                    result.append(package.get("name", manifest.parent.name) + " " + package.get("version", "") + "\n" + notice.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
    return "\n\n".join(result)


def build(output, compiler, skip_frontend=False):
    version = read_version()
    runtime = json.loads((ROOT / "desktop/runtime.json").read_text(encoding="utf-8"))
    cache = ROOT / "dev/cache"
    embed = download(runtime["python_url"], cache / Path(runtime["python_url"]).name, runtime["python_sha256"])
    if not skip_frontend:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        run([npm, "ci"], ROOT / "frontend")
        run([npm, "run", "build"], ROOT / "frontend")
    if not (ROOT / "frontend/dist/index.html").exists():
        raise RuntimeError("Build the frontend first")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="efdrr-package-") as temporary:
        work = Path(temporary)
        app = work / "EFDRR"
        python_dir = app / "runtime"
        python_dir.mkdir(parents=True)
        with zipfile.ZipFile(embed) as archive:
            archive.extractall(python_dir)
        # Resolve markers for Windows, not for the Ubuntu build host.
        records = split_lock((ROOT / "desktop/requirements-windows.lock").read_text(encoding="utf-8"))
        proxy = next(record for record in records if record.startswith("proxy-tools=="))
        binary_lock = work / "runtime.lock"
        binary_lock.write_text("\n".join(record for record in records if record != proxy) + "\n", encoding="utf-8")
        site = python_dir / "Lib/site-packages"
        run(["uv", "pip", "install", "--python-version", "3.13", "--python-platform", "x86_64-pc-windows-msvc",
             "--target", site, "--no-deps", "--require-hashes", "--only-binary", ":all:", "-r", binary_lock])
        # proxy-tools is pure Python but upstream only publishes an sdist.
        proxy_lock = work / "proxy.lock"
        proxy_lock.write_text(proxy + "\n", encoding="utf-8")
        source = work / "source"
        source.mkdir()
        run([sys.executable, "-m", "pip", "download", "--no-deps", "--require-hashes", "-r", proxy_lock, "-d", source])
        wheel_dir = work / "wheels"
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-w", wheel_dir, next(source.glob("*.tar.gz"))])
        wheel = next(wheel_dir.glob("*.whl"))
        if not wheel.name.endswith("none-any.whl"):
            raise RuntimeError("proxy-tools must remain a platform-independent wheel")
        run(["uv", "pip", "install", "--target", site, "--no-deps", wheel])
        for direct_url in site.glob("*.dist-info/direct_url.json"):
            direct_url.unlink()
        pth = next(python_dir.glob("python*._pth"))
        pth.write_text("python313.zip\n.\nLib/site-packages\n../backend\n../desktop\nimport site\n", encoding="utf-8")

        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.log")
        shutil.copytree(ROOT / "backend/app", app / "backend/app", ignore=ignore)
        shutil.copytree(ROOT / "frontend/dist", app / "frontend/dist")
        (app / "desktop").mkdir()
        for name in ("launcher.py", "tray.py", "icon.ico"):
            shutil.copy2(ROOT / "desktop" / name, app / "desktop" / name)
        shutil.copy2(ROOT / "backend/config.yaml.example", app / "backend/config.yaml.example")
        shutil.copy2(ROOT / "desktop/README.txt", app / "README.txt")
        shutil.copy2(ROOT / "VERSION", app / "VERSION")
        (app / "THIRD_PARTY_NOTICES.txt").write_text(
            "Python and Python package licenses are included in runtime/ and runtime/Lib/site-packages/*.dist-info.\n\n" + frontend_licenses(), encoding="utf-8")
        numbers = version.split("-")[0].replace(".", ",") + ",0"
        resource = work / "app.rc"
        icon = str(ROOT / "desktop/icon.ico").replace("\\", "/")
        resource.write_text('1 ICON "' + icon + '"\n1 VERSIONINFO\nFILEVERSION ' + numbers +
            '\nPRODUCTVERSION ' + numbers + '\nBEGIN\n BLOCK "StringFileInfo"\n BEGIN\n BLOCK "040904B0"\n BEGIN\n VALUE "FileDescription", "EFDRR"\n VALUE "FileVersion", "' + version +
            '"\n VALUE "ProductVersion", "' + version + '"\n END\n END\nEND\n', encoding="utf-8")
        windres = compiler.replace("gcc", "windres")
        run([windres, resource, work / "resource.o"])
        run([compiler, "-municode", "-mwindows", "-O2", "-static", "-Wl,--no-insert-timestamp", ROOT / "desktop/bootstrap.c", work / "resource.o", "-o", app / "EFDRR.exe"])
        revision = subprocess.check_output(["git", "-c", "safe.directory=" + str(ROOT), "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        (app / "BUILD-INFO.json").write_text(json.dumps({"version": version, "commit": revision, "python": runtime["python_version"], "runtime_sha256": runtime["python_sha256"]}, indent=2) + "\n", encoding="utf-8")
        archive_path = output / ("EFDRR-" + version + "-windows-x64.zip")
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(app.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(work).as_posix()
                if path.name in {".env", "config.yaml", "app.db"} or path.suffix == ".log":
                    raise RuntimeError("Runtime data in release package")
                info = zipfile.ZipInfo(relative, (2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
        (output / "SHA256SUMS.txt").write_text(sha256(archive_path) + "  " + archive_path.name + "\n", encoding="utf-8")
        shutil.copy2(ROOT / "RELEASE_NOTES.md", output / "RELEASE_NOTES.md")
        print(archive_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--compiler", default="x86_64-w64-mingw32-gcc")
    parser.add_argument("--skip-frontend", action="store_true")
    args = parser.parse_args()
    build(args.output.resolve(), args.compiler, args.skip_frontend)
