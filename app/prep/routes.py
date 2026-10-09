"""HTTP surface for the pre-production tool. Mounted by app/main.py via install().

Clients name inputs relative to the Video folder and downloads by a fixed kind.
Project ids are validated before they touch the disk. Writes go through the
local-origin middleware in main.py, which requires X-Local-Request.
"""
import logging
import re
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.config import ROOT
from app.prep import pipeline, store
from app.prep.errors import PrepError
from app.prep.params import PREVIEW_SECONDS, BatchRequest, PreviewRequest
from app.prep.paths import list_inputs, previews_root, resolve_input
from app.prep.queue import get_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/prep', tags=['prep'])
MAX_ACTIVE_JOBS = 50
PREVIEW_NAME = re.compile(r'[a-f0-9]{32}\.(mp4|m4a)')
_preview_lock = threading.Lock()


def _summary(manifest: dict) -> dict:
    keys = ('id', 'name', 'input', 'status', 'stage', 'steps', 'error', 'info',
            'summary', 'created_at', 'updated_at', 'warning', 'progress')
    data = {key: manifest.get(key) for key in keys}
    data['files'] = sorted(store.output_files(manifest).keys())
    return data


@router.get('/inputs')
def inputs():
    return {'items': list_inputs()}


@router.post('/batches')
def create_batch(request: BatchRequest):
    active = sum(1 for item in store.list_projects(limit=10_000) if item['status'] in store.ACTIVE)
    if active + len(request.inputs) > MAX_ACTIVE_JOBS:
        raise HTTPException(429, '排隊中的工作太多，請等待目前的工作完成。')
    relatives = []
    for relative in request.inputs:
        resolved = resolve_input(relative)
        relatives.append((relative, resolved.stem))
    params = request.params.model_dump()
    created = []
    for relative, name in relatives:
        manifest = store.create(relative, name, params)
        get_queue().submit(manifest['id'])
        created.append(_summary(manifest))
    return {'projects': created}


@router.get('/projects')
def projects():
    return {'projects': [_summary(item) for item in store.list_projects()]}


@router.get('/projects/{pid}')
def project(pid: str):
    return _summary(store.load(pid))


@router.post('/projects/{pid}/cancel')
def cancel(pid: str):
    return {'result': get_queue().cancel(pid)}


@router.delete('/projects/{pid}/output')
def delete_output(pid: str):
    store.delete_outputs(pid)
    return {'ok': True}


@router.get('/projects/{pid}/files/{kind}')
def download(pid: str, kind: str):
    if kind not in store.DOWNLOADS:
        raise HTTPException(404, '找不到這個檔案。')
    manifest = store.load(pid)
    path = store.output_files(manifest).get(kind)
    if path is None:
        raise HTTPException(404, '這個檔案尚未產生。')
    _, media_type = store.DOWNLOADS[kind]
    extension = path.suffix
    return FileResponse(path, media_type=media_type, filename=f"{manifest['name']}{extension}")


@router.post('/preview')
def preview(request: PreviewRequest):
    if not _preview_lock.acquire(blocking=False):
        raise HTTPException(429, '預覽正在產生中，請稍候再試。')
    try:
        # Previews only live for a day; clear expired ones here, not just at startup.
        store.cleanup_previews()
        path = pipeline.preview(request.input, request.params, cancel=threading.Event())
    finally:
        _preview_lock.release()
    return {'url': f'/api/prep/previews/{path.name}', 'seconds': PREVIEW_SECONDS}


@router.get('/previews/{name}')
def preview_file(name: str):
    if not PREVIEW_NAME.fullmatch(name):
        raise HTTPException(404, '找不到預覽。')
    path = previews_root() / name
    if not path.is_file():
        raise HTTPException(404, '預覽已過期，請重新產生。')
    media_type = 'video/mp4' if name.endswith('.mp4') else 'audio/mp4'
    return FileResponse(path, media_type=media_type)


def startup() -> dict:
    """Run once when the server starts: nothing can still be running, so clean up what is stale."""
    from app.cleanup import purge_stale_sessions
    from app.config import DATA, WORK

    return {
        'interrupted': store.mark_interrupted(),
        'intermediates_removed': store.cleanup_intermediates(),
        'previews_removed': store.cleanup_previews(),
        'sessions_removed': purge_stale_sessions(DATA / 'temp', keep=WORK),
    }


def install(app) -> None:
    app.include_router(router)

    @app.exception_handler(PrepError)
    async def prep_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.get('/prep')
    def prep_page():
        return FileResponse(ROOT / 'templates' / 'prep.html')
