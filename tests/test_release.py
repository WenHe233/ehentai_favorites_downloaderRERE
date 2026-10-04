import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from github_release import publish
from validate_package import release_assets, TARGETS, FLAVORS
from validate_package import validate
from live_acceptance import read_cookies

def test_cookie_file_accepts_existing_multiline_layout(tmp_path):
    path = tmp_path / ".env"
    path.write_text("COOKIES=\nipb_member_id=123; ipb_pass_hash=example; igneous=example2;")
    assert read_cookies(path) == {"ipb_member_id":"123", "ipb_pass_hash":"example", "igneous":"example2"}

def fake_api(assets, fail_upload=False, published=False, wrong_tag=False):
    calls = []
    remote = [{"id": i+10, "name": p.name, "size": p.stat().st_size,
        "digest": "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()} for i,p in enumerate(assets)] if published else []
    release = {"id": 1, "draft": not published, "target_commitish": "commit",
        "upload_url": "https://uploads.example.test/repos/owner/repo/releases/1/assets{?name,label}"}
    def handler(request):
        path, method = request.url.path, request.method
        calls.append((method,path))
        if "/git/ref/tags/" in path:
            return httpx.Response(200,json={"object":{"type":"commit","sha":"wrong" if wrong_tag else "commit"}}) if published or wrong_tag else httpx.Response(404)
        if path.endswith("/releases/tags/v1.1.0"):
            return httpx.Response(200,json=release) if published else httpx.Response(404)
        if path.endswith("/releases") and method == "POST":
            return httpx.Response(201,json=release)
        if path.endswith("/assets") and method == "GET":
            return httpx.Response(200,json=remote)
        if path.endswith("/assets") and method == "POST":
            if fail_upload:
                return httpx.Response(500,json={})
            item = {"id": len(remote)+1, "name": request.url.params["name"], "size":len(request.content),
                "digest":"sha256:" + hashlib.sha256(request.content).hexdigest()}
            remote.append(item)
            return httpx.Response(201,json=item)
        if method == "PATCH":
            return httpx.Response(200,json={**release,"draft":False})
        return httpx.Response(404)
    return httpx.Client(base_url="https://api.example.test",transport=httpx.MockTransport(handler)), calls

@pytest.fixture
def assets(tmp_path):
    paths = [tmp_path/"package.zip", tmp_path/"SHA256SUMS.txt"]
    for path in paths:
        path.write_bytes(b"fixture")
    return paths

@pytest.mark.parametrize("fail_upload",[True,False])
def test_draft_published_only_after_verified_uploads(assets,fail_upload):
    client,calls = fake_api(assets,fail_upload=fail_upload)
    if fail_upload:
        with pytest.raises(httpx.HTTPStatusError):
            publish(client,"owner/repo","1.1.0","commit",assets,"notes")
        assert not any(method=="PATCH" for method,_ in calls)
    else:
        publish(client,"owner/repo","1.1.0","commit",assets,"notes")
        assert calls[-1][0]=="PATCH"
        assert sum(method=="POST" and path.endswith("/assets") for method,path in calls)==2

def test_published_release_not_overwritten(assets):
    client,calls=fake_api(assets,published=True)
    publish(client,"owner/repo","1.1.0","commit",assets,"notes")
    assert all(method=="GET" for method,_ in calls)

def test_published_release_compares_content(assets):
    client,calls=fake_api(assets,published=True)
    assets[0].write_bytes(b"changed")
    with pytest.raises(ValueError,match="differs"):
        publish(client,"owner/repo","1.1.0","commit",assets,"notes")
    assert all(method=="GET" for method,_ in calls)

def test_version_cannot_move(assets):
    client,calls=fake_api(assets,wrong_tag=True)
    with pytest.raises(ValueError,match="another commit"):
        publish(client,"owner/repo","1.1.0","commit",assets,"notes")
    assert all(method=="GET" for method,_ in calls)

def test_release_requires_all_ten_packages(tmp_path,monkeypatch):
    import validate_package as module
    with pytest.raises(ValueError,match="Incomplete"):
        release_assets(tmp_path,"1.1.0","commit")
    metadata={}
    for system,arch in TARGETS:
        for flavor in FLAVORS:
            path=tmp_path/f"EFDRR-1.1.0-{flavor}-{system}-{arch}.{ 'zip' if system=='windows' else 'tar.gz'}"
            path.write_bytes(b"fixture")
            metadata[path.name]=dict(version="1.1.0",commit="commit",platform=system,arch=arch,flavor=flavor)
    monkeypatch.setattr(module,"validate",lambda p:metadata[p.name])
    assert len(release_assets(tmp_path,"1.1.0","commit"))==11
    assert len((tmp_path/"SHA256SUMS.txt").read_text().splitlines())==10
    next(iter(metadata.values()))["commit"]="other"
    with pytest.raises(ValueError,match="commit/version"):
        release_assets(tmp_path,"1.1.0","commit")


def package_fixture(path, omit=None, extra=None, wrong_arch=False):
    binary = bytearray(128)
    binary[:2] = b"MZ"
    struct.pack_into("<I", binary, 60, 80)
    binary[80:84] = b"PE\0\0"
    struct.pack_into("<H", binary, 84, 0x14c if wrong_arch else 0x8664)
    icon = b"fixture-icon"
    info = dict(version="1.1.0",commit="commit",platform="windows",arch="x64",flavor="gui",
        resources="_internal",executable="EFDRR.exe",icons={ext:hashlib.sha256(icon).hexdigest() for ext in ("ico","png","icns")})
    entries = {"BUILD-INFO.json":json.dumps(info).encode(),"VERSION":b"1.1.0", "_internal/VERSION":b"1.1.0",
        "EFDRR.exe":binary,"README.txt":b"readme","THIRD_PARTY_NOTICES.txt":b"notices",
        "_internal/frontend/dist/index.html":b"html","_internal/frontend/dist/efdrr-icon.svg":b"svg",
        "_internal/backend/config.yaml.example":b"example"}
    entries.update({"_internal/desktop/icon."+ext:icon for ext in ("ico","png","icns")})
    if omit:
        entries.pop(omit)
    if extra:
        entries[extra] = b"unexpected"
    with zipfile.ZipFile(path,"w") as archive:
        for name,content in entries.items():
            archive.writestr("EFDRR/"+name,content)


@pytest.mark.parametrize("omitted",["_internal/desktop/icon.ico","_internal/frontend/dist/index.html"])
def test_package_requires_brand_and_frontend(tmp_path,omitted):
    path=tmp_path/"package.zip"
    package_fixture(path,omit=omitted)
    with pytest.raises(ValueError,match="Missing package entry"):
        validate(path)


@pytest.mark.parametrize("extra",["../escape",".env","config.yaml","data/app.db","data/app.log"])
def test_package_rejects_runtime_data_and_traversal(tmp_path,extra):
    path=tmp_path/"package.zip"
    package_fixture(path,extra=extra)
    with pytest.raises(ValueError):
        validate(path)


def test_package_checks_binary_architecture(tmp_path):
    path=tmp_path/"package.zip"
    package_fixture(path)
    assert validate(path)["arch"]=="x64"
    package_fixture(path,wrong_arch=True)
    with pytest.raises(ValueError,match="architecture"):
        validate(path)
