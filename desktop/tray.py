"""Native tray integration, sharing the GUI event loop where required."""
import os
import subprocess
import sys
import threading
from pathlib import Path

def open_path(path):
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])

class TrayManager:
    def __init__(self, window, on_quit, downloads_dir, config_path, icon_path, disabled=False):
        self.window, self.on_quit = window, on_quit
        self.downloads_dir, self.config_path = downloads_dir, config_path
        self.icon_path = Path(icon_path)
        if not self.icon_path.is_file():
            raise FileNotFoundError(self.icon_path)
        self.disabled, self.available, self._quitting = disabled, False, False
        self._icon = None

    def prepare(self):
        if self.disabled or sys.platform.startswith("linux"):
            return
        import pystray
        from PIL import Image
        self._icon = pystray.Icon("EFDRR", Image.open(self.icon_path), "EFDRR", pystray.Menu(
            pystray.MenuItem("显示窗口", lambda: self.window.show(), default=True),
            pystray.MenuItem("打开下载目录", lambda: open_path(self.downloads_dir)),
            pystray.MenuItem("打开配置文件", lambda: open_path(self.config_path)),
            pystray.MenuItem("退出程序", self.on_quit),
        ))
        if sys.platform == "darwin":
            self._icon.run_detached()
            self.available = True

    def _qt_call(self, callback):
        from webview.platforms.qt import BrowserView
        done, errors = threading.Event(), []
        def invoke():
            try:
                callback()
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()
        BrowserView.instances[self.window.uid].create_window_trigger.emit(invoke)
        if not done.wait(10):
            raise RuntimeError("Qt tray initialization timed out")
        if errors:
            raise errors[0]

    def start(self):
        if self.disabled:
            return
        if sys.platform.startswith("linux"):
            def create():
                from PySide6.QtGui import QIcon
                from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
                QApplication.instance().setDesktopFileName("efdrr")
                if not QSystemTrayIcon.isSystemTrayAvailable():
                    return
                self._menu = QMenu()
                self._menu.addAction("显示窗口", self.window.show)
                self._menu.addAction("打开下载目录", lambda: open_path(self.downloads_dir))
                self._menu.addAction("打开配置文件", lambda: open_path(self.config_path))
                self._menu.addAction("退出程序", self.on_quit)
                self._icon = QSystemTrayIcon(QIcon(str(self.icon_path)))
                self._icon.setToolTip("EFDRR")
                self._icon.setContextMenu(self._menu)
                self._icon.activated.connect(lambda reason: self.window.show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
                self._icon.show()
                self.available = True
            self._qt_call(create)
        elif sys.platform == "win32":
            ready = threading.Event()
            def setup(icon):
                icon.visible = True
                self.available = True
                ready.set()
            threading.Thread(target=self._icon.run, kwargs={"setup": setup}, daemon=True).start()
            if not ready.wait(10):
                raise RuntimeError("Windows tray initialization timed out")

    def stop(self):
        if self._icon and not sys.platform.startswith("linux"):
            self._icon.stop()
        self.available = False

    def handle_window_closing(self):
        if self._quitting or not self.available:
            return True
        prompt = "退出程序？选择取消可隐藏到托盘，继续后台下载。"
        if sys.platform == "win32":
            import ctypes
            quit_now = ctypes.windll.user32.MessageBoxW(0, prompt, "EFDRR", 0x01 | 0x20 | 0x40000) == 1
        elif sys.platform == "darwin":
            from AppKit import NSAlert, NSAlertFirstButtonReturn
            alert = NSAlert.alloc().init()
            alert.setMessageText_("EFDRR")
            alert.setInformativeText_(prompt)
            alert.addButtonWithTitle_("退出")
            alert.addButtonWithTitle_("进入托盘")
            quit_now = alert.runModal() == NSAlertFirstButtonReturn
        else:
            from PySide6.QtWidgets import QMessageBox
            quit_now = QMessageBox.question(None, "EFDRR", prompt, QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Ok
        if quit_now:
            self._quitting = True
            return True
        self.window.hide()
        return False
