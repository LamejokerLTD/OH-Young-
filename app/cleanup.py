"""Remove only the isolated media session after the server process exits."""
import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


def remove_session(directory):
    directory = Path(directory).resolve()
    if directory.parent.name != 'temp' or not re.fullmatch(r'session-[a-f0-9]{32}', directory.name):
        raise ValueError('Invalid session directory')
    if directory.exists():
        shutil.rmtree(directory)


def purge_stale_sessions(temp_dir, keep, max_age_hours=24):
    """Remove session folders left behind by a crash or power loss. The live session is kept."""
    temp_dir = Path(temp_dir)
    if not temp_dir.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for entry in temp_dir.iterdir():
        if entry.name == Path(keep).name or not entry.is_dir() or entry.is_symlink():
            continue
        if not re.fullmatch(r'session-[a-f0-9]{32}', entry.name):
            continue
        if entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def start_watcher(directory):
    if os.name == 'nt':
        return subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), str(os.getpid()), str(directory)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )


def watch(pid, directory):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)
    elif ctypes.get_last_error() != 87:
        return  # Do not delete if process existence cannot be established.
    for _ in range(120):
        try:
            remove_session(directory)
            return
        except OSError:
            time.sleep(1)


if __name__ == '__main__':
    watch(int(sys.argv[1]), sys.argv[2])
