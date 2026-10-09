"""Project folders, manifests and retention.

Layout under Video/projects/<id>/:
  manifest.json   status, parameters, per-step state, output names
  intermediate/   extracted audio, filter graph, scratch files (deleted after 7 days)
  output/         render, transcript and cut lists (kept until deleted by hand)
"""
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from app.prep.errors import PrepError
from app.prep.paths import check_project_id, previews_root, projects_root

logger = logging.getLogger(__name__)

INTERMEDIATE_DAYS = 7
PREVIEW_HOURS = 24
ACTIVE = ('queued', 'running')
STEPS = ('probe', 'silence', 'render', 'transcript', 'cutlist')

# Whitelist of downloadable names: the client picks a kind, never a path.
DOWNLOADS = {
    'render': ('render.mp4', 'video/mp4'),
    'render-audio': ('render.m4a', 'audio/mp4'),
    'cutlist.edl': ('cutlist.edl', 'text/plain; charset=utf-8'),
    'cutlist.fcpxml': ('cutlist.fcpxml', 'application/xml; charset=utf-8'),
    'cutlist.xml': ('cutlist.xml', 'application/xml; charset=utf-8'),
    'transcript.srt': ('transcript/transcript.srt', 'text/plain; charset=utf-8'),
    'transcript.vtt': ('transcript/transcript.vtt', 'text/vtt; charset=utf-8'),
    'transcript.txt': ('transcript/transcript.txt', 'text/plain; charset=utf-8'),
    'transcript.timed.txt': ('transcript/transcript.timed.txt', 'text/plain; charset=utf-8'),
    'transcript.json': ('transcript/transcript.json', 'application/json; charset=utf-8'),
}


def _now() -> float:
    return time.time()


def project_dir(pid: str, root: Path | None = None) -> Path:
    return projects_root(root) / check_project_id(pid)


def _write_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(f'.{uuid.uuid4().hex}.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def save(manifest: dict, root: Path | None = None) -> None:
    manifest['updated_at'] = _now()
    _write_json(project_dir(manifest['id'], root) / 'manifest.json', manifest)


def load(pid: str, root: Path | None = None) -> dict:
    path = project_dir(pid, root) / 'manifest.json'
    if not path.is_file():
        raise PrepError('找不到這個專案。')
    return json.loads(path.read_text(encoding='utf-8'))


def create(input_path: str, name: str, params: dict, root: Path | None = None) -> dict:
    pid = uuid.uuid4().hex
    folder = projects_root(root) / pid
    (folder / 'intermediate').mkdir(parents=True)
    (folder / 'output').mkdir(parents=True)
    manifest = {
        'id': pid,
        'input': input_path,
        'name': name,
        'params': params,
        'status': 'queued',
        'stage': '等待處理',
        'steps': {step: 'pending' for step in STEPS},
        'info': None,
        'summary': None,
        'outputs': [],
        'error': None,
        'created_at': _now(),
        'updated_at': _now(),
    }
    save(manifest, root)
    return manifest


def list_projects(root: Path | None = None, limit: int = 200) -> list[dict]:
    found = []
    for path in projects_root(root).iterdir():
        if not path.is_dir() or path.name == 'previews':
            continue
        try:
            found.append(load(path.name, root))
        except (PrepError, ValueError, OSError):
            continue
    found.sort(key=lambda item: item.get('created_at', 0), reverse=True)
    return found[:limit]


def mark_interrupted(root: Path | None = None) -> int:
    """At startup nothing can still be running; unfinished jobs are reported as interrupted."""
    count = 0
    for manifest in list_projects(root, limit=10_000):
        if manifest['status'] in ACTIVE:
            manifest['status'] = 'failed'
            manifest['stage'] = '已中斷'
            manifest['error'] = '程式重新啟動，這個工作已中斷；請重新送出。'
            save(manifest, root)
            count += 1
    return count


def output_files(manifest: dict, root: Path | None = None) -> dict[str, Path]:
    """Map download kind -> file, only for files that exist."""
    base = project_dir(manifest['id'], root) / 'output'
    found = {}
    for kind, (relative, _) in DOWNLOADS.items():
        path = base / relative
        if path.is_file():
            found[kind] = path
    return found


def delete_outputs(pid: str, root: Path | None = None) -> None:
    manifest = load(pid, root)
    if manifest['status'] in ACTIVE:
        raise PrepError('這個工作仍在處理中，無法刪除成品。')
    shutil.rmtree(project_dir(pid, root) / 'output', ignore_errors=True)
    (project_dir(pid, root) / 'output').mkdir(parents=True, exist_ok=True)
    manifest['outputs'] = []
    manifest['steps'] = {step: 'pending' for step in STEPS}
    manifest['summary'] = None
    manifest['status'] = 'deleted'
    manifest['stage'] = '成品已刪除'
    save(manifest, root)


def cleanup_intermediates(root: Path | None = None, now: float | None = None) -> int:
    """Remove scratch files older than the retention window. Outputs are never touched."""
    cutoff = (now or _now()) - INTERMEDIATE_DAYS * 86400
    removed = 0
    for manifest in list_projects(root, limit=10_000):
        if manifest['status'] in ACTIVE:
            continue
        folder = project_dir(manifest['id'], root) / 'intermediate'
        if folder.is_dir() and manifest.get('updated_at', 0) < cutoff:
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(exist_ok=True)
            removed += 1
    return removed


def cleanup_previews(root: Path | None = None, now: float | None = None) -> int:
    cutoff = (now or _now()) - PREVIEW_HOURS * 3600
    removed = 0
    for path in previews_root(root).iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
