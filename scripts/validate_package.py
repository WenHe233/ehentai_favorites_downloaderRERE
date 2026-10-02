import hashlib
import json
import sys
import zipfile
from pathlib import Path


def validate(path):
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        for required in ("EFDRR/EFDRR.exe", "EFDRR/runtime/pythonw.exe", "EFDRR/VERSION", "EFDRR/frontend/dist/index.html", "EFDRR/backend/app/main.py", "EFDRR/desktop/launcher.py"):
            if required not in names:
                raise ValueError("Missing package entry: " + required)
        for name in names:
            parts = Path(name).parts
            if ".." in parts or Path(name).is_absolute() or Path(name).name in {".env", "config.yaml", "app.db"}:
                raise ValueError("Unsafe package entry: " + name)
        if not archive.read("EFDRR/EFDRR.exe").startswith(b"MZ"):
            raise ValueError("Launcher is not a Windows executable")
        metadata = json.loads(archive.read("EFDRR/BUILD-INFO.json"))
        if archive.read("EFDRR/VERSION").decode().strip() != metadata["version"]:
            raise ValueError("Package version mismatch")
        if archive.testzip():
            raise ValueError("Package ZIP validation failed")
        return metadata


if __name__ == "__main__":
    print(json.dumps(validate(Path(sys.argv[1])), indent=2))
