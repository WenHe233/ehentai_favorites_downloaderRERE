"""Exercise a built image, including persisted configuration across recreation."""
import argparse
import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from smoke_package import wait_ready, verify_http

def docker(*args):
    return subprocess.check_output(["docker", *map(str,args)], text=True).strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--platform", required=True)
    args = parser.parse_args()
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    with tempfile.TemporaryDirectory(prefix="efdrr-container-") as temp:
        data = Path(temp).resolve()
        for iteration in range(2):
            name = "efdrr-test-" + uuid.uuid4().hex[:12]
            docker("run", "-d", "--name", name, "--platform", args.platform,
                "-p", "127.0.0.1::8000", "-v", str(data) + ":/app/userdata", args.image)
            try:
                port = docker("port", name, "8000/tcp").rsplit(":",1)[1]
                url = "http://127.0.0.1:" + port
                wait_ready(url, timeout=150)
                verify_http(url, data, version, expected_limit=2 if iteration else None)
                docker("stop", "--time", "40", name)
                assert "Application shutdown complete" in docker("logs", name)
            finally:
                docker("rm", "-f", name)
    print(json.dumps(dict(image=args.image, platform=args.platform, success=True)))

if __name__ == "__main__":
    main()
