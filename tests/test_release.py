import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gitea_release import publish
from live_acceptance import Budget, read_cookies


def test_cookie_file_accepts_existing_multiline_layout(tmp_path):
    path=tmp_path/".env"
    path.write_text("COOKIES=\nipb_member_id=123; ipb_pass_hash=example; igneous=example2;",encoding="utf-8")
    assert read_cookies(path)=={"ipb_member_id":"123","ipb_pass_hash":"example","igneous":"example2"}


def fake_api(fail_upload=False, published=False, wrong_tag=False):
    calls=[]
    def handler(request):
        path=request.url.path; method=request.method; calls.append((method,path))
        if path.endswith('/tags/v1.0.0') and '/releases/' not in path:
            return httpx.Response(200,json={"commit":{"sha":"wrong" if wrong_tag else "commit"}}) if published or wrong_tag else httpx.Response(404)
        if path.endswith('/releases/tags/v1.0.0'):
            return httpx.Response(200,json={"id":1,"draft":False,"assets":[{"name":"package.zip"},{"name":"SHA256SUMS.txt"}]}) if published else httpx.Response(404)
        if path.endswith('/tags'):return httpx.Response(201,json={})
        if path.endswith('/releases'):return httpx.Response(201,json={"id":1,"draft":True,"assets":[]})
        if path.endswith('/assets'):return httpx.Response(500 if fail_upload else 201,json={"id":2})
        if method=='PATCH':return httpx.Response(200,json={"id":1,"draft":False})
        return httpx.Response(404)
    return httpx.Client(base_url='https://example.test/api/v1',transport=httpx.MockTransport(handler)),calls


@pytest.mark.parametrize('fail_upload',[True,False])
def test_draft_is_published_only_after_all_uploads(tmp_path,fail_upload):
    assets=[tmp_path/'package.zip',tmp_path/'SHA256SUMS.txt']
    for path in assets:path.write_bytes(b'fixture')
    client,calls=fake_api(fail_upload=fail_upload)
    if fail_upload:
        with pytest.raises(httpx.HTTPStatusError):publish(client,'owner/repo','1.0.0','commit',assets,'notes')
        assert not any(method=='PATCH' for method,_ in calls)
    else:
        publish(client,'owner/repo','1.0.0','commit',assets,'notes')
        assert calls[-1][0]=='PATCH'
        assert sum(method=='POST' and path.endswith('/assets') for method,path in calls)==2


def test_published_release_is_not_overwritten(tmp_path):
    client,calls=fake_api(published=True)
    publish(client,'owner/repo','1.0.0','commit',[tmp_path/'package.zip',tmp_path/'SHA256SUMS.txt'],'notes')
    assert all(method=='GET' for method,_ in calls)


def test_version_cannot_move_to_another_commit(tmp_path):
    client,calls=fake_api(wrong_tag=True)
    with pytest.raises(ValueError,match='another commit'):publish(client,'owner/repo','1.0.0','commit',[], 'notes')
    assert all(method=='GET' for method,_ in calls)
