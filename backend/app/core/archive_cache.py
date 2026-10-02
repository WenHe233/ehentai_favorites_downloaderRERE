import hashlib
import errno
import json
import os
import shutil
import zipfile
from pathlib import Path


class ArchiveCache:
    """A complete archive survives destination errors, never a change of identity."""
    def __init__(self, path: Path, gid: int, token: str, quality: str):
        self.path = path
        self.metadata = path.with_suffix(".json")
        self.identity = {"gid": gid, "token": token, "quality": quality}

    def digest(self):
        with self.path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def valid(self):
        try:
            metadata = json.loads(self.metadata.read_text(encoding="utf-8"))
            return all(metadata.get(key) == value for key, value in self.identity.items()) and metadata.get("sha256") == self.digest()
        except (OSError, ValueError):
            return False

    def mark_complete(self):
        with zipfile.ZipFile(self.path) as archive:
            if not archive.namelist() or archive.testzip():
                raise ValueError("归档为空或校验失败")
        temporary = self.metadata.with_suffix(".tmp")
        temporary.write_text(json.dumps({**self.identity, "sha256": self.digest()}), encoding="utf-8")
        os.replace(temporary, self.metadata)

    def forget(self):
        self.metadata.unlink(missing_ok=True)

    def publish(self, destination):
        """Replace the destination only after a complete cross-volume copy."""
        destination = Path(destination)
        try:
            os.replace(self.path, destination)
        except OSError as exc:
            if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
                raise
            temporary = destination.with_name(destination.name + ".tmpdownload")
            try:
                shutil.copyfile(self.path, temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            self.path.unlink(missing_ok=True)
        self.forget()
