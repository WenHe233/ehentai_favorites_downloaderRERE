"""Shared bootstrap for frozen, source and container entry points."""
import os
import sys
from pathlib import Path


def resource_root():
    return Path(os.environ.get("EFDRR_RESOURCE_ROOT") or getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()


def portable_root():
    if not getattr(sys, "frozen", False):
        return resource_root()
    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix == ".app":
            return parent.parent
    return executable.parent


def configure(data_root=None):
    resources = resource_root()
    data = Path(data_root or os.environ.get("EFDRR_DATA_ROOT") or portable_root()).resolve()
    data.mkdir(parents=True, exist_ok=True)
    (data / "data").mkdir(exist_ok=True)
    os.environ["EFDRR_RESOURCE_ROOT"] = str(resources)
    os.environ["EFDRR_DATA_ROOT"] = str(data)
    sys.path.insert(0, str(resources / "backend"))
    return resources, data


class InstanceLock:
    """OS-owned lock, released on crash as well as clean exit; never unlink it."""
    def __init__(self, data_root):
        self.path = Path(data_root) / "data" / "instance.lock"
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise RuntimeError(f"此数据目录已被其他 EFDRR 实例使用：{self.path.parent.parent}") from exc
        return self

    def __exit__(self, *args):
        if self.stream:
            self.stream.close()
            self.stream = None
