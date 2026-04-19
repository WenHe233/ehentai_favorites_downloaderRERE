"""
Automated build script for the EHentai Favorites Downloader desktop app.

Usage:
    python desktop/build.py

Steps:
    1. Build the React frontend  (npm install && npm run build)
    2. Run PyInstaller with the .spec file
    3. Copy config.yaml.example into the output folder for convenience

Requirements:
    - Node.js / npm  (for frontend build)
    - Python packages: pyinstaller, pywebview, pystray, Pillow
      plus all backend dependencies from backend/requirements.txt
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DESKTOP_DIR = PROJECT_ROOT / "desktop"
SPEC_FILE = DESKTOP_DIR / "ehentai_downloader.spec"
OUTPUT_DIR = PROJECT_ROOT / "dist" / "ehentai_downloader"


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"\n{'='*60}")
    print(f"  Running: {' '.join(cmd)}")
    print(f"  CWD:     {cwd or '.'}")
    print(f"{'='*60}\n")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"\nERROR: Command failed with exit code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def build_frontend() -> None:
    print("\n[1/3] Building frontend...")

    dist = FRONTEND_DIR / "dist"
    if dist.is_dir() and (dist / "index.html").exists():
        print("  Frontend dist/ already exists, skipping rebuild. Delete it to force a rebuild.")
        return

    # Check npm is available
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    if shutil.which(npm_cmd) is None:
        print("ERROR: npm is not installed or not on PATH.", file=sys.stderr)
        sys.exit(1)

    _run([npm_cmd, "install"], cwd=FRONTEND_DIR)
    _run([npm_cmd, "run", "build"], cwd=FRONTEND_DIR)

    dist = FRONTEND_DIR / "dist"
    if not dist.is_dir():
        print("ERROR: Frontend build did not produce a dist/ directory.", file=sys.stderr)
        sys.exit(1)
    print("  Frontend build complete.")


def run_pyinstaller() -> None:
    """Run PyInstaller using a temporary distpath to avoid Windows directory locks.

    On Windows, VS Code file watchers (or other tools) can hold a handle on
    the output directory, making it impossible to delete.  By writing to a
    fresh temp directory first, we sidestep that entirely, then copy the
    result to the final location.
    """
    print("\n[2/3] Running PyInstaller...")

    with tempfile.TemporaryDirectory(prefix="ehd_dist_") as tmp_dist:
        _run(
            [
                sys.executable, "-m", "PyInstaller",
                "--clean", "--noconfirm",
                "--distpath", tmp_dist,
                str(SPEC_FILE),
            ],
            cwd=PROJECT_ROOT,
        )

        built = Path(tmp_dist) / "ehentai_downloader"
        if not built.is_dir():
            print("ERROR: PyInstaller did not produce the expected output.", file=sys.stderr)
            sys.exit(1)

        # Remove old output dir (best-effort)
        if OUTPUT_DIR.exists():
            print(f"  Removing previous output: {OUTPUT_DIR}")
            try:
                shutil.rmtree(OUTPUT_DIR)
            except PermissionError:
                # Last resort: clear contents, rename stub
                for child in list(OUTPUT_DIR.iterdir()):
                    try:
                        shutil.rmtree(child) if child.is_dir() else child.unlink()
                    except PermissionError:
                        pass
                stub = OUTPUT_DIR.with_name(OUTPUT_DIR.name + "_old")
                try:
                    if stub.exists():
                        shutil.rmtree(stub)
                except PermissionError:
                    pass
                try:
                    OUTPUT_DIR.rename(stub)
                except PermissionError:
                    print("  WARNING: Could not remove old output dir. Merging in-place.")

        # Move (or copy) fresh build to final location
        if not OUTPUT_DIR.exists():
            shutil.copytree(built, OUTPUT_DIR)
        else:
            # Merge into the existing (empty) directory
            for child in built.iterdir():
                dest = OUTPUT_DIR / child.name
                if child.is_dir():
                    shutil.copytree(child, dest)
                else:
                    shutil.copy2(child, dest)

    print("  PyInstaller build complete.")


def copy_extras() -> None:
    print("\n[3/3] Copying extras to output...")

    # Copy config.yaml.example alongside the exe for user convenience
    example_cfg = PROJECT_ROOT / "backend" / "config.yaml.example"
    if example_cfg.exists():
        dest = OUTPUT_DIR / "config.yaml.example"
        shutil.copy2(example_cfg, dest)
        print(f"  Copied {example_cfg.name} -> {dest}")

    print("  Done.")


def main() -> None:
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Output dir:   {OUTPUT_DIR}")

    build_frontend()
    run_pyinstaller()
    copy_extras()

    print(f"\n{'='*60}")
    print(f"  BUILD SUCCESSFUL")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Run:    {OUTPUT_DIR / 'ehentai_downloader.exe'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
