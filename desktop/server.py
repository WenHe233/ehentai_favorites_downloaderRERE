"""Headless server entry point; also used by the container."""
import argparse
import sys
from pathlib import Path

from desktop_runtime import InstanceLock, configure, resource_root


def port_number(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv=None):
    parser = argparse.ArgumentParser(description="EFDRR 网页与 API 服务器")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=port_number, default=8000)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--log-level", choices=["debug", "info", "warning", "error"], default="info")
    parser.add_argument("--version", action="version", version=(resource_root() / "VERSION").read_text().strip())
    args = parser.parse_args(argv)
    _, data = configure(args.data_root)
    with InstanceLock(data):
        import uvicorn
        from app.main import app
        print(f"EFDRR: http://{args.host}:{args.port}\n配置与初始登录信息：{data / 'config.yaml'}", flush=True)
        server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, workers=1,
            loop="asyncio", http="h11", ws="none", log_level=args.log_level, timeout_graceful_shutdown=20))
        server.run()
        return 0 if server.started else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
