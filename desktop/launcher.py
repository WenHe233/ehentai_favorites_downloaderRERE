"""
Desktop launcher for EHentai Favorites Downloader.

Starts the FastAPI backend in a background thread, then opens a pywebview
native window pointing at the local server.  A system-tray icon (via pystray)
lets the user minimise-to-tray or quit.
"""

import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

# ── Fix None stdio for windowed (console=False) PyInstaller builds ──
# On Windows, when console=False, sys.stdout/stderr are None.
# Any write (print, logging, loguru, uvicorn) will crash with AttributeError.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# ── Ensure the backend package is importable ────────────────────
# In dev mode the backend code lives at  <project>/backend/app/…
# In frozen (PyInstaller) mode everything is already on sys.path via _MEIPASS.
if not getattr(sys, "frozen", False):
    _backend_dir = Path(__file__).resolve().parent.parent / "backend"
    if _backend_dir.is_dir() and str(_backend_dir) not in sys.path:
        sys.path.insert(0, str(_backend_dir))


def _find_free_port() -> int:
    """Ask the OS to assign an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 30.0) -> bool:
    """Poll the backend until it responds or *timeout* seconds elapse."""
    import urllib.request
    import urllib.error

    url = f"http://127.0.0.1:{port}/api/v1/auth/config"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


class _JsonServer:
    """Thin wrapper that stores the uvicorn Server so we can shut it down."""

    def __init__(self, port: int):
        self.port = port
        self._server = None

    def run(self) -> None:
        import uvicorn
        # Import the actual ASGI app object instead of using a string reference.
        # String-based import ("app.main:app") fails inside a PyInstaller bundle.
        from app.main import app as asgi_app
        config = uvicorn.Config(
            asgi_app,
            host="127.0.0.1",
            port=self.port,
            log_level="info",
        )
        self._server = uvicorn.Server(config)
        self._server.run()

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


def main() -> None:
    port = _find_free_port()

    # ── Start backend in a daemon thread ─────────────────────────
    server = _JsonServer(port)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not _wait_for_server(port):
        print("ERROR: Backend server failed to start within 30 seconds.", file=sys.stderr)
        sys.exit(1)

    # ── Resolve user-facing directories (for tray menu) ──────────
    from app.core.config import settings

    downloads_dir = settings.DOWNLOAD_DIR
    config_path = settings.CONFIG_PATH

    # ── Import GUI libraries after backend is ready ──────────────
    import webview
    from tray import TrayManager

    url = f"http://127.0.0.1:{port}"

    window = webview.create_window(
        title="Ehentai Favorites Downloader RERE",
        url=url,
        width=1280,
        height=800,
        min_size=(800, 500),
    )

    # ── Quit callback shared by tray and window ──────────────────
    def do_quit() -> None:
        server.shutdown()
        tray.stop()
        window.destroy()

    tray = TrayManager(
        window=window,
        on_quit=do_quit,
        downloads_dir=downloads_dir,
        config_path=config_path,
    )

    # Intercept the window close button
    window.events.closing += tray.handle_window_closing

    # Start tray icon after the webview event-loop begins
    def on_webview_started() -> None:
        tray.start()

    webview.start(func=on_webview_started, debug=False)

    # webview.start() blocks until all windows are destroyed.
    # If we reach here, ensure everything is torn down.
    server.shutdown()
    tray.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Write crash info next to the exe so user can report it.
        if getattr(sys, "frozen", False):
            log_path = Path(sys.executable).parent / "crash.log"
        else:
            log_path = Path(__file__).parent / "crash.log"
        with open(log_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise
