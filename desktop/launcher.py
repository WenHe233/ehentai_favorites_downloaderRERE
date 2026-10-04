"""Portable desktop host for Windows, macOS and Linux."""
import argparse
import ctypes
import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from desktop_runtime import InstanceLock, configure, resource_root

ROOT = resource_root()
sys.path.insert(0, str(ROOT / "backend"))


def message(text, error=False):
    if sys.platform == "win32":
        return ctypes.windll.user32.MessageBoxW(0, text, "EFDRR", 0x10 if error else 0x40)
    if sys.platform == "darwin":
        from AppKit import NSAlert
        alert = NSAlert.alloc().init()
        alert.setMessageText_("EFDRR")
        alert.setInformativeText_(text)
        alert.runModal()
    elif error:
        print(text, file=sys.stderr)


def set_app_identity():
    if sys.platform == "win32":
        shell = ctypes.WinDLL("shell32")
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        if shell.SetCurrentProcessExplicitAppUserModelID("WenHe233.EFDRR.GUI") < 0:
            raise RuntimeError("无法设置 Windows 应用标识")
    elif sys.platform.startswith("linux"):
        os.environ["QT_API"] = "pyside6"


def webview_available():
    import winreg
    key = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for access in (winreg.KEY_READ | winreg.KEY_WOW64_32KEY, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, key, 0, access) as handle:
                    version, _ = winreg.QueryValueEx(handle, "pv")
                    if version and version != "0.0.0.0":
                        return True
            except OSError:
                pass
    return False


class BackendServer:
    def __init__(self, data_root):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port_file = data_root / "data" / "desktop-port.json"
        try:
            port = int(json.loads(port_file.read_text(encoding="utf-8"))["port"])
        except (OSError, ValueError, KeyError, TypeError):
            port = 0
        if not 1024 <= port <= 65535:
            port = 0
        try:
            self.socket.bind(("127.0.0.1", port))
        except OSError:
            self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        port_file.write_text(json.dumps({"port": self.port}), encoding="utf-8")
        self.server = None
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        try:
            import uvicorn
            from app.main import app
            self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", loop="asyncio", http="h11", ws="none", timeout_graceful_shutdown=20))
            self.server.run(sockets=[self.socket])
        except BaseException as exc:
            self.error = str(exc)
            traceback.print_exc()

    def wait(self):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and self.thread.is_alive():
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/v1/health", timeout=1) as response:
                    if json.load(response)["status"] == "ok":
                        return True
            except (OSError, ValueError):
                time.sleep(.2)
        return False

    def stop(self):
        if self.server:
            self.server.should_exit = True
        self.thread.join(timeout=30)
        self.socket.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--version", action="version", version=(ROOT / "VERSION").read_text().strip())
    parser.add_argument("--smoke-test", type=Path, help="Write a GUI acceptance report and exit")
    args = parser.parse_args()
    set_app_identity()
    _, data_root = configure(args.data_root)
    log_dir = data_root / "data"
    log_dir.mkdir(exist_ok=True)
    # pythonw has no standard streams. Keep diagnostics available locally.
    if sys.stdout is None:
        sys.stdout = (log_dir / "desktop.log").open("a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout

    lock = InstanceLock(data_root)
    lock.__enter__()

    server = None
    tray = None
    try:
        if sys.platform == "win32" and not webview_available():
            message("需要安装 Microsoft Edge WebView2 Runtime。\n安装完成后请重新打开 EFDRR。", error=True)
            import webbrowser
            webbrowser.open("https://developer.microsoft.com/microsoft-edge/webview2/")
            return 1
        server = BackendServer(data_root)
        server.thread.start()
        if not server.wait():
            raise RuntimeError(server.error or "后端启动超时，请检查 data/desktop.log")
        from app.core.config import settings
        from app.core.runtime import VERSION
        import webview
        from tray import TrayManager
        if settings.initial_credentials and not args.smoke_test and not sys.platform.startswith("linux"):
            username, password = settings.initial_credentials
            message(f"首次登录信息\n\n用户名：{username}\n密码：{password}\n\n可在程序旁的 config.yaml 中查看或修改。")
            settings.initial_credentials = None
        window = webview.create_window("EFDRR " + VERSION, f"http://127.0.0.1:{server.port}", width=1280, height=850, min_size=(820, 560))

        def quit_app():
            tray._quitting = True
            window.destroy()

        tray = TrayManager(window, quit_app, settings.DOWNLOAD_DIR, settings.CONFIG_PATH, ROOT / "desktop/icon.png", disabled=args.no_tray)
        tray.prepare()
        window.events.closing += tray.handle_window_closing

        def started():
            tray.start()
            if not args.smoke_test:
                if sys.platform.startswith("linux") and settings.initial_credentials:
                    username, password = settings.initial_credentials
                    window.create_confirmation_dialog("首次登录信息", f"用户名：{username}\n密码：{password}\n配置：{settings.CONFIG_PATH}")
                    settings.initial_credentials = None
                return
            report = {"version": VERSION, "health": True, "window": False, "login": False, "tray": False, "routes": []}
            try:
                deadline = time.monotonic() + 40
                submitted = False
                while time.monotonic() < deadline:
                    if not submitted and window.evaluate_js("Boolean(document.querySelector('input[name=password]'))"):
                        credentials = {"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD}
                        window.evaluate_js("const credentials = " + json.dumps(credentials) + "; for (const [name, value] of Object.entries(credentials)) { document.querySelector(`input[name=${name}]`).value = value; } document.querySelector('form').requestSubmit();")
                        submitted = True
                    if window.evaluate_js("Boolean(document.querySelector('a[href=\"/galleries\"]'))"):
                        break
                    time.sleep(.25)
                else:
                    raise RuntimeError("桌面前端未完成加载")
                report["window"] = True
                report["login"] = submitted
                window.hide()
                time.sleep(.5)
                window.show()
                report["tray"] = tray.available
                report["tray_expected"] = not args.no_tray
                report["brand"] = bool(window.evaluate_js("document.querySelector('[data-brand=efdrr]')?.getAttribute('src') === '/efdrr-icon.svg'"))
                if not report["brand"]:
                    raise RuntimeError("品牌图标未加载")
                if sys.platform == "win32":
                    from System import Action
                    from System.Drawing import Icon
                    def inspect_icon():
                        expected = Icon(str(ROOT / "desktop/icon.ico")).ToBitmap()
                        actual = window.native.Icon.ToBitmap()
                        report["window_icon"] = actual.Size == expected.Size and all(
                            actual.GetPixel(x, y).ToArgb() == expected.GetPixel(x, y).ToArgb()
                            for x in range(expected.Width) for y in range(expected.Height))
                        actual.Dispose()
                        expected.Dispose()
                    window.native.Invoke(Action(inspect_icon))
                    app_id = ctypes.c_wchar_p()
                    shell = ctypes.WinDLL("shell32")
                    shell.GetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
                    shell.GetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
                    result = shell.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(app_id))
                    report["app_id"] = app_id.value if result == 0 else None
                    if app_id:
                        ole = ctypes.WinDLL("ole32")
                        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
                        ole.CoTaskMemFree(ctypes.cast(app_id, ctypes.c_void_p))
                    if not report["window_icon"] or report["app_id"] != "WenHe233.EFDRR.GUI" or (not args.no_tray and not tray.available):
                        raise RuntimeError("窗口或托盘图标缺失")
                for route, expected in (("/galleries", "下载任务"), ("/settings", "设置"), ("/", "收藏与下载")):
                    window.load_url(f"http://127.0.0.1:{server.port}{route}")
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        if window.evaluate_js("document.querySelector('h1')?.textContent") == expected:
                            report["routes"].append(route)
                            break
                        time.sleep(.25)
                    else:
                        raise RuntimeError("路由加载失败：" + route)
                report["success"] = True
            except BaseException as exc:
                report["success"] = False
                report["error"] = str(exc)
            finally:
                args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
                args.smoke_test.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                quit_app()

        renderer = "edgechromium" if sys.platform == "win32" else "cocoa" if sys.platform == "darwin" else "qt"
        extension = "ico" if sys.platform == "win32" else "icns" if sys.platform == "darwin" else "png"
        webview.start(func=started, gui=renderer, icon=str(ROOT / ("desktop/icon." + extension)), debug=False, private_mode=False, storage_path=str(log_dir / "webview"))
        if args.smoke_test:
            return 0 if args.smoke_test.exists() and json.loads(args.smoke_test.read_text())["success"] else 1
        return 0
    finally:
        if tray:
            tray.stop()
        if server:
            server.stop()
        lock.__exit__(None, None, None)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        destination = Path(os.environ.get("EFDRR_DATA_ROOT", ROOT)) / "data"
        destination.mkdir(parents=True, exist_ok=True)
        with (destination / "desktop-crash.log").open("w", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        if "--smoke-test" in sys.argv:
            report = Path(sys.argv[sys.argv.index("--smoke-test") + 1])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"success": False, "error": str(exc)}), encoding="utf-8")
        else:
            message("启动失败：" + str(exc) + "\n详细信息见 data/desktop-crash.log。", error=True)
        raise SystemExit(1)
