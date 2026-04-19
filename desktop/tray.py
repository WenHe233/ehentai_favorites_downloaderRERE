"""
System tray icon manager for the desktop GUI.

Provides:
- Tray icon with right-click menu (show window / open downloads / open config / quit)
- Double-click tray icon to restore window
- Close-button interception: prompt user to minimize-to-tray or quit
"""

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import pystray
from PIL import Image

if TYPE_CHECKING:
    import webview


def _load_icon() -> Image.Image:
    """Load the application icon, falling back to a generated one."""
    # Try loading from bundled resources or dev location
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys._MEIPASS) / "icon.ico")  # type: ignore[attr-defined]
    candidates.append(Path(__file__).parent / "icon.ico")

    for path in candidates:
        if path.exists():
            return Image.open(path)

    # Fallback: generate a simple colored icon
    img = Image.new("RGB", (64, 64), color=(70, 130, 180))
    return img


class TrayManager:
    """Manages the system tray icon and its interactions with the pywebview window."""

    def __init__(
        self,
        window: "webview.Window",
        on_quit: Callable[[], None],
        downloads_dir: Optional[Path] = None,
        config_path: Optional[Path] = None,
    ):
        self._window = window
        self._on_quit = on_quit
        self._downloads_dir = downloads_dir
        self._config_path = config_path
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the tray icon in a background thread."""
        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", self._show_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开下载目录", self._open_downloads),
            pystray.MenuItem("打开配置文件", self._open_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出程序", self._quit),
        )

        self._icon = pystray.Icon(
            name="ehentai_downloader",
            icon=_load_icon(),
            title="Ehentai Favorites Downloader RERE",
            menu=menu,
        )

        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop and remove the tray icon."""
        if self._icon is not None:
            self._icon.stop()

    def handle_window_closing(self) -> bool:
        """
        Called when the user clicks the window close button.
        Shows a JS confirm dialog asking whether to minimize or quit.

        Returns:
            True  -> allow the window to close (quit)
            False -> prevent closing (minimize to tray instead)
        """
        # NOTE: We must NOT call window.evaluate_js() here because the
        # closing callback runs on the GUI thread and evaluate_js also
        # dispatches to the GUI thread, causing a deadlock.
        # Use a native Windows MessageBox instead.
        import ctypes
        MB_OKCANCEL = 0x01
        MB_ICONQUESTION = 0x20
        MB_TOPMOST = 0x40000
        IDOK = 1
        result = ctypes.windll.user32.MessageBoxW(
            0,
            "确定 = 退出程序\n取消 = 最小化到系统托盘（后台继续运行）",
            "Ehentai Favorites Downloader RERE",
            MB_OKCANCEL | MB_ICONQUESTION | MB_TOPMOST,
        )

        if result == IDOK:
            # User chose "OK" = quit
            return True
        else:
            # User chose "Cancel" = minimize to tray
            self._window.hide()
            return False

    # ── Menu actions ─────────────────────────────────────────────

    def _show_window(self, icon: pystray.Icon = None, item: pystray.MenuItem = None) -> None:
        self._window.show()

    def _open_downloads(self, icon: pystray.Icon = None, item: pystray.MenuItem = None) -> None:
        if self._downloads_dir and self._downloads_dir.exists():
            os.startfile(str(self._downloads_dir))

    def _open_config(self, icon: pystray.Icon = None, item: pystray.MenuItem = None) -> None:
        if self._config_path and self._config_path.exists():
            os.startfile(str(self._config_path))

    def _quit(self, icon: pystray.Icon = None, item: pystray.MenuItem = None) -> None:
        self._on_quit()
