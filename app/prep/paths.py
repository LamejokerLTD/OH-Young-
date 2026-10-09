"""Video root, project layout and input-path validation.

Every path that reaches the disk from an HTTP request passes through here.
Clients name inputs by a path relative to the Video folder; they never supply
absolute paths, and symlinks or files inside the projects folder are refused.
"""
import os
import re
from pathlib import Path

from app.config import ROOT
from app.prep.errors import PrepError

ALLOWED_INPUT = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4a', '.mp3', '.wav', '.aac', '.flac'}
PROJECTS = 'projects'
PREVIEWS = 'previews'
PROJECT_ID = re.compile(r'[a-f0-9]{32}')
MAX_INPUTS_PER_BATCH = 20
MAX_LISTED_INPUTS = 500


def video_root() -> Path:
    override = os.environ.get('WHISPER_VIDEO_ROOT')
    root = (Path(override) if override else ROOT / 'Video').resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def projects_root(root: Path | None = None) -> Path:
    path = (root or video_root()) / PROJECTS
    path.mkdir(parents=True, exist_ok=True)
    return path


def previews_root(root: Path | None = None) -> Path:
    path = projects_root(root) / PREVIEWS
    path.mkdir(parents=True, exist_ok=True)
    return path


def check_project_id(value: str) -> str:
    if not isinstance(value, str) or not PROJECT_ID.fullmatch(value):
        raise PrepError('找不到這個專案。')
    return value


def resolve_input(relative: str, root: Path | None = None) -> Path:
    """Map a client-supplied relative name to a real media file inside the Video folder."""
    root = (root or video_root()).resolve()
    if not isinstance(relative, str) or not relative or len(relative) > 500 or '\x00' in relative:
        raise PrepError('輸入檔案名稱不正確。')
    if relative.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', relative) or '..' in Path(relative).parts:
        raise PrepError('輸入檔案必須位於 Video 資料夾之內。')
    lexical = root / relative
    if lexical.is_symlink():
        raise PrepError('不接受符號連結。')
    resolved = lexical.resolve()
    if not resolved.is_relative_to(root) or resolved.is_relative_to(root / PROJECTS):
        raise PrepError('輸入檔案必須位於 Video 資料夾之內。')
    if resolved.suffix.lower() not in ALLOWED_INPUT:
        raise PrepError('不支援的檔案格式。')
    if not resolved.is_file():
        raise PrepError('找不到輸入檔案，請確認已放入 Video 資料夾。')
    return resolved


def list_inputs(root: Path | None = None) -> list[dict]:
    root = (root or video_root()).resolve()
    skip = root / PROJECTS
    found = []
    for directory, subdirs, files in os.walk(root):
        current = Path(directory)
        subdirs[:] = [d for d in subdirs if not (current / d).is_symlink() and (current / d) != skip]
        for name in files:
            path = current / name
            if path.suffix.lower() not in ALLOWED_INPUT or path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            found.append({
                'path': path.relative_to(root).as_posix(),
                'name': path.name,
                'size': size,
            })
            if len(found) >= MAX_LISTED_INPUTS:
                return sorted(found, key=lambda item: item['path'])
    return sorted(found, key=lambda item: item['path'])
