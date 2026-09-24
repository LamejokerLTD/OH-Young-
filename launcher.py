import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

HOST = '127.0.0.1'
PORT_CANDIDATES = range(8000, 8006)
URL = 'http://127.0.0.1:8000'
BACKEND_VERSION = 'LOCAL-WHISPER-20260924-R1'

LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = LAUNCHER_DIR

# Make `import app.main` and `import uvicorn` work regardless of the current
# working directory (e.g. when launched from a shortcut).
if LAUNCHER_DIR not in sys.path:
    sys.path.insert(0, LAUNCHER_DIR)


def _ensure_stdlib_streams():
    """pythonw.exe starts with sys.stdout/sys.stderr set to None.

    Uvicorn (and its logging setup) assumes usable streams, so give them line
    buffered UTF-8 append log files under the project logs directory before any
    Uvicorn import/setup happens.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        logs_dir = os.path.join(PROJECT_ROOT, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        if sys.stdout is None:
            sys.stdout = open(os.path.join(logs_dir, 'launcher.out.log'),
                              'a', encoding='utf-8', buffering=1)
        if sys.stderr is None:
            sys.stderr = open(os.path.join(logs_dir, 'launcher.err.log'),
                              'a', encoding='utf-8', buffering=1)
    except OSError:
        # Never let logging setup break startup; fall back to devnull streams.
        if sys.stdout is None:
            sys.stdout = open(os.devnull, 'w', encoding='utf-8', buffering=1)
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w', encoding='utf-8', buffering=1)


_ensure_stdlib_streams()


def is_existing_app(port=None):
    """Reuse only a server started from this installation and code version."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = f'http://{HOST}:{port}' if port is not None else URL
        with opener.open(url + '/api/debug', timeout=3) as response:
            info = json.load(response)
        return (
            info.get('backend_version') == BACKEND_VERSION
            and os.path.normcase(os.path.realpath(info.get('root', '')))
            == os.path.normcase(os.path.realpath(PROJECT_ROOT))
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def open_browser():
    for _ in range(120):
        try:
            with socket.create_connection((HOST, int(URL.rsplit(':', 1)[1])), timeout=.5):
                webbrowser.open(URL)
                return
        except OSError:
            time.sleep(.5)


def main():
    global URL
    port = None
    for candidate in PORT_CANDIDATES:
        with socket.socket() as sock:
            sock.settimeout(1)
            occupied = sock.connect_ex((HOST, candidate)) == 0
        if occupied and is_existing_app(candidate):
            port = candidate
            URL = f'http://{HOST}:{port}'
            print('Local Whisper is already running. Opening the existing page...')
            webbrowser.open(URL)
            return 0
        if not occupied:
            port = candidate
            URL = f'http://{HOST}:{port}'
            break
    if port is None:
        print('Ports 8000-8005 are all used by other applications. Please close one and try again.')
        return 1
    import uvicorn
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run('app.main:app', host=HOST, port=port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
