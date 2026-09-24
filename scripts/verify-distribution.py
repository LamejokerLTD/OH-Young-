"""Independent smoke test of an unpacked release using actual pythonw.

No model is loaded. A synthetic completed job exercises the real export API.
Only the child server created here is terminated.
"""
import argparse
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import time
import urllib.request


def child(root, port):
    assert sys.stdout is None and sys.stderr is None, 'Expected actual pythonw streams'
    runpy.run_path(str(root / 'launcher.py'), run_name='distribution_smoke')
    assert sys.stdout is not None and sys.stderr is not None
    for stream in (sys.stdout, sys.stderr):
        assert Path(stream.name).resolve().parent == (root / 'logs').resolve()
    from app.main import app, manager
    from app.config import WORK
    from app.subtitle import export
    job_id = 'd' * 32
    manager.jobs[job_id] = {'id': job_id, 'file': 'installation-test.wav', 'extension': '.wav', 'status': 'done'}
    destination = WORK / 'outputs' / job_id
    destination.mkdir()
    export({'segments': [], 'subtitles': [{'start': 0, 'end': 1, 'text': '安裝測試'}]}, destination)
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=port, access_log=False)


def parent(root):
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    assert pythonw.is_file()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    environment = dict(os.environ)
    environment['WHISPER_DATA'] = str(root / 'smoke-runtime')
    process = subprocess.Popen(
        [str(pythonw), str(Path(__file__).resolve()), str(root), '--child-port', str(port)],
        cwd=root.parent, env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f'http://127.0.0.1:{port}'
    try:
        deadline = time.monotonic() + 45
        while True:
            try:
                with opener.open(base + '/openapi.json', timeout=2) as response:
                    schema = json.load(response)
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f'Background service failed, exit={process.poll()}; check {root / "logs"}')
                time.sleep(.25)
        assert '/api/jobs/{id}/download/{format}' in schema['paths']
        with opener.open(base, timeout=5) as response:
            assert 'downloads' in response.read().decode('utf-8')
        for format_name in ('srt', 'txt', 'timed.txt', 'vtt', 'json'):
            with opener.open(base + '/api/jobs/' + 'd' * 32 + '/download/' + format_name, timeout=5) as response:
                assert response.status == 200
                assert 'attachment' in response.headers['Content-Disposition']
                assert '安裝測試' in response.read().decode('utf-8')
        assert process.poll() is None
        print('PASS: actual pythonw startup from another cwd, project-local logs, homepage, five download formats.')
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--child-port', type=int)
    args = parser.parse_args()
    if args.child_port:
        child(args.root.resolve(), args.child_port)
    else:
        parent(args.root.resolve())
