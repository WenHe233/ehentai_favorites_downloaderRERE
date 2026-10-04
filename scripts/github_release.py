"""Publish complete, verified assets; failed uploads remain a draft."""
import argparse
import os
import re
import subprocess
from pathlib import Path
import httpx
from version import ROOT, read_version
from validate_package import digest, release_assets

def version_changed(before, after, event):
    if event == "workflow_dispatch":
        return True
    if not before or set(before) == {"0"}:
        return True
    if not re.fullmatch(r"[a-f0-9]{40}", before) or not re.fullmatch(r"[a-f0-9]{40}", after):
        raise ValueError("Invalid commit identity")
    return bool(subprocess.check_output(["git", "diff", "--name-only", before, after, "--", "VERSION"], cwd=ROOT).strip())

def publish(client, repository, version, revision, assets, notes):
    prefix = "/repos/" + repository
    tag = "v" + version
    def request(method, path, **kwargs):
        response = client.request(method, prefix + path, **kwargs)
        if response.status_code == 404 and method == "GET":
            return None
        response.raise_for_status()
        return response.json() if response.content else None
    existing = request("GET", "/git/ref/tags/" + tag)
    if existing:
        obj = existing["object"]
        while obj["type"] == "tag":
            obj = request("GET", "/git/tags/" + obj["sha"])["object"]
        if obj["type"] != "commit" or obj["sha"] != revision:
            raise ValueError("Version tag already points to another commit")
    release = request("GET", "/releases/tags/" + tag)
    if release and release["draft"] and release["target_commitish"] != revision and not existing:
        raise ValueError("Draft belongs to another commit")
    if not release:
        release = request("POST", "/releases", json={"tag_name": tag, "target_commitish": revision,
            "name": tag, "body": notes, "draft": True, "prerelease": "-" in version})
    release_path = "/releases/" + str(release["id"])
    remote = []
    page = 1
    while True:
        batch = request("GET", release_path + "/assets", params={"per_page": 100, "page": page}) or []
        remote.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    existing_assets = {asset["name"]: asset for asset in remote}
    if not release["draft"]:
        if set(existing_assets) != {path.name for path in assets}:
            raise ValueError("Published release does not have the expected files")
        for path in assets:
            asset = existing_assets[path.name]
            if asset.get("size") != path.stat().st_size or asset.get("digest") != "sha256:" + digest(path):
                raise ValueError("Published release differs; refusing to overwrite")
        return release
    for name, asset in existing_assets.items():
        request("DELETE", "/releases/assets/" + str(asset["id"]))
    upload_url = release["upload_url"].split("{")[0]
    for path in assets:
        with path.open("rb") as stream:
            response = client.post(upload_url, params={"name": path.name}, content=stream,
                headers={"Content-Type": "application/octet-stream", "Content-Length": str(path.stat().st_size)})
        response.raise_for_status()
        uploaded = response.json()
        if uploaded.get("size") != path.stat().st_size or uploaded.get("digest") != "sha256:" + digest(path):
            raise ValueError("Uploaded asset checksum mismatch: " + path.name)
    return request("PATCH", release_path, json={"draft": False, "body": notes, "make_latest": "false" if "-" in version else "true"})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-change", action="store_true")
    parser.add_argument("--assets", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    version = read_version()
    revision = os.environ.get("GITHUB_SHA") or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if args.check_change:
        changed = version_changed(os.environ.get("BEFORE_SHA", ""), revision, os.environ.get("GITHUB_EVENT_NAME", "push"))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"changed={str(changed).lower()}\nversion={version}\n")
        return
    assets = release_assets(args.assets, version, revision)
    notes = ROOT / "RELEASE_NOTES.md"
    image = f"ghcr.io/{os.environ['GITHUB_REPOSITORY'].lower()}"
    body = notes.read_text(encoding="utf-8") + f"\n\n容器镜像：`{image}:{version}`\n"
    with httpx.Client(base_url="https://api.github.com", headers={
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, timeout=300) as client:
        release = publish(client, os.environ["GITHUB_REPOSITORY"], version, revision, assets + [notes], body)
    print(release["html_url"])

if __name__ == "__main__":
    main()
