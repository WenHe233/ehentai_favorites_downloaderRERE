"""Inspect release archives without extracting executable content."""
import hashlib
import json
import posixpath
import struct
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

TARGETS = [(system, arch) for system, arch in [
    ("windows", "x64"), ("linux", "x64"), ("linux", "arm64"), ("macos", "x64"), ("macos", "arm64")]]
FLAVORS = ("cli", "gui")

def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def validate(path):
    path = Path(path)
    archive = zipfile.ZipFile(path) if path.suffix == ".zip" else tarfile.open(path)
    with archive:
        zipped = isinstance(archive, zipfile.ZipFile)
        entries = archive.infolist() if zipped else archive.getmembers()
        names = [item.filename if zipped else item.name for item in entries]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive members")
        for item, name in zip(entries, names):
            parts = PurePosixPath(name).parts
            if not parts or parts[0] != "EFDRR" or ".." in parts or "\\" in name or ":" in name:
                raise ValueError("Unsafe package entry: " + name)
            if any(p in {".env", "config.yaml", "app.db", "downloads", "native_resume"} or p.endswith(".log") for p in parts):
                raise ValueError("Runtime data in package: " + name)
            if not zipped:
                if item.issym():
                    link = posixpath.normpath(posixpath.join(posixpath.dirname(name), item.linkname))
                    if not link.startswith("EFDRR/") or item.linkname.startswith("/"):
                        raise ValueError("Unsafe package link")
                elif not item.isfile() and not item.isdir():
                    raise ValueError("Unsupported archive member")
        def read(name):
            full = "EFDRR/" + name
            if full not in names:
                raise ValueError("Missing package entry: " + full)
            return archive.read(full) if zipped else archive.extractfile(full).read()
        metadata = json.loads(read("BUILD-INFO.json"))
        if (metadata["platform"], metadata["arch"]) not in TARGETS or metadata["flavor"] not in FLAVORS:
            raise ValueError("Unsupported release target")
        if read("VERSION").decode().strip() != metadata["version"]:
            raise ValueError("Package version mismatch")
        resources = metadata["resources"]
        if read(resources + "/VERSION").decode().strip() != metadata["version"]:
            raise ValueError("Bundled version mismatch")
        for name in ("frontend/dist/index.html", "frontend/dist/efdrr-icon.svg", "backend/config.yaml.example"):
            read(resources + "/" + name)
        for ext, expected in metadata["icons"].items():
            if hashlib.sha256(read(resources + "/desktop/icon." + ext)).hexdigest() != expected:
                raise ValueError("Brand icon checksum mismatch")
        if set(metadata["icons"]) != {"ico", "png", "icns"}:
            raise ValueError("Missing brand icon")
        read("README.txt")
        read("THIRD_PARTY_NOTICES.txt")
        binary = read(metadata["executable"])
        system, arch = metadata["platform"], metadata["arch"]
        if system == "windows":
            if binary[:2] != b"MZ":
                raise ValueError("Invalid PE executable")
            offset = struct.unpack_from("<I", binary, 60)[0]
            if binary[offset:offset+4] != b"PE\0\0" or struct.unpack_from("<H", binary, offset+4)[0] != 0x8664:
                raise ValueError("Wrong PE architecture")
        elif system == "linux":
            if binary[:4] != b"\x7fELF" or struct.unpack_from("<H", binary, 18)[0] != (183 if arch == "arm64" else 62):
                raise ValueError("Wrong ELF architecture")
        else:
            if binary[:4] != b"\xcf\xfa\xed\xfe" or struct.unpack_from("<I", binary, 4)[0] != (0x100000c if arch == "arm64" else 0x1000007):
                raise ValueError("Wrong Mach-O architecture")
        if not zipped and not archive.getmember("EFDRR/" + metadata["executable"]).mode & 0o111:
            raise ValueError("Executable permission missing")
        if zipped and archive.testzip():
            raise ValueError("ZIP validation failed")
        return metadata

def release_assets(directory, version, revision):
    directory = Path(directory)
    expected = {f"EFDRR-{version}-{flavor}-{system}-{arch}" + (".zip" if system == "windows" else ".tar.gz")
        for system, arch in TARGETS for flavor in FLAVORS}
    actual = {p.name for p in directory.iterdir() if p.name.endswith((".zip", ".tar.gz"))}
    if actual != expected:
        raise ValueError(f"Incomplete release: missing={expected-actual}, extra={actual-expected}")
    packages = [directory / name for name in sorted(expected)]
    for package in packages:
        info = validate(package)
        if info["version"] != version or info["commit"] != revision:
            raise ValueError("Package commit/version mismatch")
        expected_name = f"EFDRR-{version}-{info['flavor']}-{info['platform']}-{info['arch']}"
        if not package.name.startswith(expected_name + "."):
            raise ValueError("Package target/name mismatch")
    checksum = directory / "SHA256SUMS.txt"
    checksum.write_text("".join(digest(p) + "  " + p.name + "\n" for p in packages), encoding="utf-8")
    return packages + [checksum]

if __name__ == "__main__":
    import sys
    print(json.dumps(validate(Path(sys.argv[1])), indent=2))
