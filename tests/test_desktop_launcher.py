import os
import socket
import subprocess
import sys
import uuid

import pytest

import desktop_launcher


def free_port():
    with socket.socket() as sock:
        sock.bind((desktop_launcher.HOST, 0))
        return sock.getsockname()[1]


def test_choose_port_skips_occupied(monkeypatch):
    with socket.socket() as occupied:
        occupied.bind((desktop_launcher.HOST, 0))
        occupied.listen()
        blocked = occupied.getsockname()[1]
        available = free_port()
        monkeypatch.setattr(desktop_launcher, "PORT_CANDIDATES", (blocked, available))
        assert desktop_launcher.choose_port() == available


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex")
def test_single_instance_rejection_and_release():
    name = rf"Local\LocalWhisperDesktopTest-{uuid.uuid4().hex}"
    first = desktop_launcher.SingleInstance(name)
    second = desktop_launcher.SingleInstance(name)
    third = desktop_launcher.SingleInstance(name)
    try:
        assert first.acquire()
        assert not second.acquire()
        first.release()
        assert third.acquire()
    finally:
        first.release()
        second.release()
        third.release()


def test_shutdown_timeout_is_reported():
    class Server:
        should_exit = False

    class Thread:
        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.timeout = timeout

    backend = desktop_launcher.BackendController(free_port())
    backend.server = Server()
    backend.thread = Thread()
    assert not backend.stop(timeout=0.01)
    assert backend.server.should_exit
    assert backend.thread.timeout == 0.01


def test_finish_shutdown_waits_for_active_job(monkeypatch):
    backend = desktop_launcher.BackendController(free_port())
    states = iter((True, True, False))
    sleeps = []
    stop_timeouts = []
    monkeypatch.setattr(backend, "has_active_jobs", lambda: next(states))
    monkeypatch.setattr(desktop_launcher.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        backend,
        "stop",
        lambda timeout: stop_timeouts.append(timeout) or True,
    )

    assert backend.finish_shutdown()
    assert sleeps == [0.25, 0.25]
    assert stop_timeouts == [desktop_launcher.FINAL_SHUTDOWN_TIMEOUT]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (desktop_launcher.DesktopError("Local Whisper 背景服務啟動逾時。"), "背景服務啟動逾時"),
        (ModuleNotFoundError("No module named 'webview'", name="webview"), "webview"),
        (RuntimeError("EdgeChromium runtime unavailable"), "WebView2 Runtime"),
        (RuntimeError("internal token-like detail"), "Local Whisper 啟動失敗"),
    ],
)
def test_friendly_error_hides_technical_details(error, expected):
    message = desktop_launcher.friendly_error(error)
    assert expected in message
    assert "internal token-like detail" not in message


def test_backend_ready_shutdown_and_port_release():
    port = free_port()
    code = (
        "from desktop_launcher import BackendController; "
        f"backend=BackendController({port}); "
        "backend.start(); print('ready', flush=True); "
        "assert backend.stop(timeout=15); print('stopped', flush=True)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=desktop_launcher.PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    assert "ready" in result.stdout
    assert "stopped" in result.stdout
    with socket.socket() as sock:
        assert sock.connect_ex((desktop_launcher.HOST, port)) != 0
