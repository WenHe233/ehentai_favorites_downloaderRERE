"""Publish a tested package. A failed upload leaves a draft, never a partial release."""
import argparse
import hashlib
import os
import re
import subprocess
from pathlib import Path

import httpx

from version import ROOT, read_version
from validate_package import validate


def version_changed(before, after, event):
    if event == "workflow_dispatch":
        return True
    if not before or set(before) == {"0"}:
        return (ROOT / "VERSION").exists()
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

    existing_tag = request("GET", "/tags/" + tag)
    if existing_tag and existing_tag["commit"]["sha"] != revision:
        raise ValueError("Version tag already points to another commit")
    release = request("GET", "/releases/tags/" + tag)
    if release and not release["draft"]:
        names = {asset["name"] for asset in release.get("assets", [])}
        if not {path.name for path in assets}.issubset(names):
            raise ValueError("Published release is missing expected files; refusing to overwrite")
        return release
    if not existing_tag:
        request("POST", "/tags", json={"tag_name": tag, "target": revision, "message": "EFDRR " + version})
    if not release:
        release = request("POST", "/releases", json={"tag_name": tag, "target_commitish": revision, "name": tag, "body": notes, "draft": True, "prerelease": "-" in version})
    release_path = "/releases/" + str(release["id"])
    existing_assets = {asset["name"]: asset for asset in release.get("assets", [])}
    for path in assets:
        if path.name in existing_assets:
            request("DELETE", release_path + "/assets/" + str(existing_assets[path.name]["id"]))
        with path.open("rb") as stream:
            request("POST", release_path + "/assets", params={"name": path.name}, files={"attachment": (path.name, stream, "application/octet-stream")})
    return request("PATCH", release_path, json={"draft": False, "body": notes})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-change", action="store_true")
    parser.add_argument("--assets", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    version = read_version()
    revision = os.environ.get("GITEA_SHA") or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if args.check_change:
        changed = version_changed(os.environ.get("BEFORE_SHA", ""), revision, os.environ.get("GITEA_EVENT_NAME", "push"))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("changed=" + str(changed).lower() + "\n")
    else:
        archive = args.assets / ("EFDRR-" + version + "-windows-x64.zip")
        metadata = validate(archive)
        if metadata["commit"] != revision or metadata["version"] != version:
            raise ValueError("Release candidate does not match the current commit/version")
        checksum = args.assets / "SHA256SUMS.txt"
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum.read_text(encoding="utf-8").strip() != digest + "  " + archive.name:
            raise ValueError("Release checksum mismatch")
        server = os.environ["GITEA_SERVER_URL"].rstrip("/")
        with httpx.Client(base_url=server + "/api/v1", headers={"Authorization": "token " + os.environ["GITEA_TOKEN"]}, timeout=300) as client:
            release = publish(client, os.environ["GITEA_REPOSITORY"], version, revision, [archive, checksum], (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8"))
        print(release["html_url"])
