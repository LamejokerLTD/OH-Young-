"""Minimal Windows Desktop Prototype for Local Whisper.

This keeps the existing browser launcher untouched.  The backend runs in a
background thread in this process and pywebview provides the native window.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

HOST = "127.0.0.1"
PORT_CANDIDATES = range(8000, 8006)
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_VERSION = "LOCAL-WHISPER-20260924-R1"
MUTEX_NAME = r"Local\LocalWhisperDesktop"
SHUTDOWN_TIMEOUT = 15
FINAL_SHUTDOWN_TIMEOUT = 5
DESKTOP_VERSION = "Phase 3"
DEBUG_MODE = os.environ.get("LOCAL_WHISPER_DESKTOP_DEBUG") == "1"
LOG_PATH = PROJECT_ROOT / "logs" / "desktop.log"
logger = logging.getLogger("local_whisper.desktop")


class DesktopError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        if DEBUG_MODE:
            logger.addHandler(logging.StreamHandler(sys.stderr))


class SingleInstance:
    """Windows-owned mutex; the OS releases it after crashes or process exit."""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self.handle = None

    def acquire(self) -> bool:
        if os.name != "nt":
            raise RuntimeError("Local Whisper Desktop currently requires Windows.")

        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]

        handle = kernel.CreateMutexW(None, False, self.name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "Could not create single-instance mutex")
        if ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS:
            kernel.CloseHandle(handle)
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        import ctypes

        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self.handle)
        self.handle = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Local Whisper is already running.")
        return self

    def __exit__(self, *_exc_info) -> None:
        self.release()


def choose_port() -> int:
    for port in PORT_CANDIDATES:
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex((HOST, port)) != 0:
                return port
    raise DesktopError("Local Whisper 找不到可使用的本機連接埠。")


def debug_info(port: int) -> dict:
    url = f"http://{HOST}:{port}/api/debug"
    with urllib.request.urlopen(url, timeout=1.5) as response:
        return json.load(response)


class BackendController:
    def __init__(self, port: int) -> None:
        self.port = port
        self.server = None
        self.thread: threading.Thread | None = None
        self.start_error: Exception | None = None

    def _run(self) -> None:
        try:
            self.server.run()
        except Exception as exc:
            self.start_error = exc
            logger.exception("Backend thread failed on port %s", self.port)

    def start(self) -> None:
        import uvicorn

        config = uvicorn.Config(
            "app.main:app",
            host=HOST,
            port=self.port,
            log_level="info",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self._run,
            name="local-whisper-backend",
            daemon=True,
        )
        self.thread.start()

        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.thread is not None and not self.thread.is_alive():
                raise DesktopError("Local Whisper 無法啟動背景服務。") from self.start_error
            try:
                info = debug_info(self.port)
                root = Path(info.get("root", "")).resolve()
                if (
                    info.get("status") == "ok"
                    and info.get("backend_version") == BACKEND_VERSION
                    and root == PROJECT_ROOT
                ):
                    return
            except (OSError, ValueError, TypeError) as exc:
                last_error = exc
            time.sleep(0.25)

        self.stop()
        detail = f": {last_error}" if last_error else ""
        logger.error("Backend ready timeout on port %s%s", self.port, detail)
        raise DesktopError("Local Whisper 背景服務啟動逾時。")

    def stop(self, timeout: float = SHUTDOWN_TIMEOUT) -> bool:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=timeout)
        return self.thread is None or not self.thread.is_alive()

    def wait(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            self.thread.join()

    def has_active_jobs(self) -> bool:
        """Read the in-process manager without changing the backend API."""
        from app.main import manager

        with manager.lock:
            return any(
                job.get("status") in {"queued", "running"}
                for job in manager.jobs.values()
            )

    def finish_shutdown(self) -> bool:
        """Wait for accepted work, then give Uvicorn one final exit window."""
        while self.has_active_jobs():
            time.sleep(0.25)
        return self.stop(timeout=FINAL_SHUTDOWN_TIMEOUT)


def show_message(message: str, *, error: bool = False) -> None:
    """Small native message for startup errors; no JS bridge is exposed."""
    if os.name == "nt":
        import ctypes

        icon = 0x10 if error else 0x40
        ctypes.windll.user32.MessageBoxW(None, message, "Local Whisper", icon)
    else:
        print(message, file=sys.stderr if error else sys.stdout)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, DesktopError):
        return exc.message
    if isinstance(exc, (ModuleNotFoundError, ImportError)):
        missing = getattr(exc, "name", None) or str(exc)
        return f"Local Whisper 缺少必要元件：{missing}。\n請執行 install.bat 後再試一次。"
    if "webview" in str(exc).lower() or "edgechromium" in str(exc).lower():
        return "Local Whisper 無法開啟桌面視窗。\n請檢查 Microsoft Edge WebView2 Runtime。"
    return "Local Whisper 啟動失敗。\n請查看專案 logs 資料夾中的 desktop.log。"


def show_waiting_notice() -> None:
    threading.Thread(
        target=show_message,
        args=("Local Whisper 正在完成目前的轉錄工作，完成後將自動關閉。",),
        name="local-whisper-shutdown-notice",
        daemon=True,
    ).start()


def main() -> int:
    instance = SingleInstance()
    backend = None
    try:
        configure_logging()
        logger.info("Desktop start; version=%s; backend_version=%s; python=%s", DESKTOP_VERSION, BACKEND_VERSION, sys.version.split()[0])
        if not instance.acquire():
            logger.info("Duplicate instance rejected")
            show_message("Local Whisper 已經在執行中。")
            return 0

        from app.data_directory import (
            DataDirectoryError,
            ModelCacheError,
            ensure_desktop_model,
            resolve_data_root,
            resolve_model_cache,
        )

        try:
            data_root = resolve_data_root(mode="desktop")
        except DataDirectoryError as exc:
            raise DesktopError("Local Whisper 無法存取應用程式資料目錄。") from exc
        try:
            model_cache = resolve_model_cache(mode="desktop")
            model_path = ensure_desktop_model(model_cache, PROJECT_ROOT)
        except ModelCacheError as exc:
            raise DesktopError(
                "Local Whisper 找不到可用的 Whisper 模型快取。\n"
                "請確認原有模型仍存在，或稍後執行模型安裝流程。"
            ) from exc
        os.environ["WHISPER_DATA"] = str(data_root)
        os.environ["WHISPER_MODEL_CACHE"] = str(model_cache)
        logger.info("Selected data root=%s", data_root)
        logger.info("Selected model cache=%s", model_cache)
        logger.info("Validated model snapshot=%s", model_path)

        import webview

        port = choose_port()
        logger.info("Selected port=%s; host=%s", port, HOST)
        backend = BackendController(port)
        logger.info("Backend start requested")
        backend.start()
        logger.info("Backend ready; port=%s", port)
        try:
            webview.create_window(
                "Local Whisper",
                f"http://{HOST}:{port}/",
                width=1280,
                height=800,
                resizable=True,
                maximized=False,
            )
            logger.info("WebView start")
            webview.start(gui="edgechromium", debug=False)
        except Exception as exc:
            raise DesktopError(
                "Local Whisper 無法開啟桌面視窗。\n請檢查 Microsoft Edge WebView2 Runtime。"
            ) from exc
        finally:
            logger.info("Shutdown requested")
            if backend.has_active_jobs():
                logger.info("Waiting for active job")
                show_waiting_notice()
            if not backend.stop():
                logger.info("Backend shutdown waiting for accepted work")
                if not backend.finish_shutdown():
                    logger.warning("Work complete; runtime threads remain after shutdown grace period")
            logger.info("Backend shutdown complete")
        return 0
    except Exception as exc:
        logger.exception("Desktop startup failed")
        show_message(friendly_error(exc), error=True)
        return 1
    finally:
        if backend is not None:
            backend.stop(timeout=1)
        instance.release()
        logger.info("Desktop exit")


if __name__ == "__main__":
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
