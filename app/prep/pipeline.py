"""One project end to end. Step order is fixed: probe -> silence -> render -> transcript -> cut lists.

Transcripts are produced from the rendered file, so their timestamps match the
delivered video (after cuts and speed change), not the original recording.
"""
import logging
import shutil
import uuid
from pathlib import Path

from opencc import OpenCC

from app.audio import extract
from app.prep import cutlist, store
from app.prep.errors import PrepCancelled, PrepError
from app.prep.media import MediaInfo, detect_silence, probe
from app.prep.params import PREVIEW_SECONDS, Params
from app.prep.paths import resolve_input, video_root
from app.prep.render import render
from app.subtitle import export, subtitles
from app.transcriber import NoAlignment

logger = logging.getLogger(__name__)


def _info_dict(info: MediaInfo) -> dict:
    return {
        'duration': round(info.duration, 3),
        'has_video': info.has_video,
        'width': info.width,
        'height': info.height,
        'fps': f'{info.fps.numerator}/{info.fps.denominator}' if info.has_video else None,
        'audio_channels': info.audio_channels,
        'audio_rate': info.audio_rate,
    }


def _keep(info: MediaInfo, params: Params, source: Path, scratch: Path, cancel, limit=None):
    span = min(limit, info.duration) if limit else info.duration
    if not params.silence.enabled:
        return [(0.0, span)], False
    silences = detect_silence(
        source,
        threshold_db=params.silence.threshold_db,
        min_silence=params.silence.min_silence,
        limit=limit,
        duration=span,
        log_dir=scratch,
        cancel=cancel,
    )
    keep = cutlist.keep_segments(span, silences, params.silence.pad)
    if not keep:
        raise PrepError('整段影片都被判定為靜音，請調低靜音門檻後重試。')
    return keep, True


def _ensure_disk_space(target_dir: Path, source: Path) -> None:
    """Refuse to start a render that could fill the disk. Rule of thumb: output <= source size."""
    needed = int(source.stat().st_size * 1.5) + 2 * 1024**3
    if shutil.disk_usage(target_dir).free < needed:
        raise PrepError('磁碟空間不足，請先釋放空間或更換保存位置後再處理。')


def run(manifest: dict, provider, cancel, root: Path | None = None) -> None:
    root = root or video_root()
    params = Params.model_validate(manifest['params'])
    source = resolve_input(manifest['input'], root)
    folder = store.project_dir(manifest['id'], root)
    scratch = folder / 'intermediate'
    output = folder / 'output'

    def begin(step: str, text: str):
        if cancel.is_set():
            raise PrepCancelled()
        manifest['steps'][step] = 'running'
        manifest['stage'] = text
        store.save(manifest, root)

    def finish(step: str, status: str = 'done'):
        manifest['steps'][step] = status
        store.save(manifest, root)

    begin('probe', '正在讀取媒體資訊')
    info = probe(source, log_dir=scratch, cancel=cancel)
    manifest['info'] = _info_dict(info)
    finish('probe')

    begin('silence', '正在偵測靜音')
    keep, cut = _keep(info, params, source, scratch, cancel)
    finish('silence', 'done' if cut else 'skipped')

    kept_seconds = sum(end - start for start, end in keep)
    speed = params.speed
    summary = {
        'kept_seconds': round(kept_seconds, 3),
        'removed_seconds': round(info.duration - kept_seconds, 3),
        'output_seconds': round(kept_seconds / speed, 3),
        'segments': len(keep),
        'speed': speed,
    }
    manifest['summary'] = summary
    store.save(manifest, root)

    media_for_text = source
    if params.needs_render:
        _ensure_disk_space(output, source)
        begin('render', '正在渲染影片（降噪、EQ、變速、H.264 編碼）')
        name = 'render.mp4' if info.has_video else 'render.m4a'
        target = output / name
        render(source, target, keep, params, info, work_dir=scratch, cancel=cancel)
        media_for_text = target
        finish('render')
    else:
        manifest['steps']['render'] = 'skipped'
        store.save(manifest, root)

    if params.transcript.enabled:
        begin('transcript', '正在辨識逐字稿')
        wav = scratch / 'transcript-16k.wav'
        extract(media_for_text, wav)
        duration = manifest['info']['duration']

        def update(**values):
            if cancel.is_set():
                raise PrepCancelled()
            if 'processed' in values and duration:
                manifest['progress'] = min(1.0, values['processed'] / duration)
                store.save(manifest, root)
            if 'stage' in values:
                manifest['stage'] = values['stage']
            if values.get('warning'):
                manifest['warning'] = values['warning']
                store.save(manifest, root)

        language = None if params.transcript.language == 'auto' else params.transcript.language
        segments, detected, probability, device = provider.transcribe(wav, language, update)
        segments = NoAlignment().align(wav, segments)
        convert = OpenCC('s2twp').convert if params.transcript.traditional else (lambda text: text)
        for segment in segments:
            segment['display_text'] = convert(segment['text'])
        result = dict(
            file=manifest['name'],
            duration=duration,
            language=detected,
            language_probability=probability,
            model='large-v3',
            device=device,
            compute_type='float16' if device == 'cuda' else 'int8',
            segments=segments,
            subtitles=subtitles(segments, convert),
            conversion='s2twp' if params.transcript.traditional else None,
            processing_mode='prep',
        )
        (output / 'transcript').mkdir(parents=True, exist_ok=True)
        export(result, output / 'transcript')
        finish('transcript')
    else:
        manifest['steps']['transcript'] = 'skipped'
        store.save(manifest, root)

    begin('cutlist', '正在產生剪輯清單')
    name = Path(manifest['input']).stem
    (output / 'cutlist.edl').write_text(cutlist.edl(name, info.fps or 30, keep), encoding='utf-8')
    if info.has_video:
        (output / 'cutlist.fcpxml').write_text(cutlist.fcpxml(name, source, info, keep), encoding='utf-8')
        (output / 'cutlist.xml').write_text(cutlist.premiere(name, source, info, keep), encoding='utf-8')
    finish('cutlist')

    manifest['outputs'] = sorted(store.output_files(manifest, root))
    manifest['stage'] = '完成'
    manifest.pop('progress', None)


def preview(source_relative: str, params: Params, cancel, root: Path | None = None) -> Path:
    """Render the first PREVIEW_SECONDS with the same settings. Transcripts are not produced."""
    root = root or video_root()
    source = resolve_input(source_relative, root)
    scratch = store.previews_root(root) / f'work-{uuid.uuid4().hex}'
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        info = probe(source, log_dir=scratch, cancel=cancel)
        keep, _ = _keep(info, params, source, scratch, cancel, limit=PREVIEW_SECONDS)
        extension = '.mp4' if info.has_video else '.m4a'
        target = store.previews_root(root) / f'{uuid.uuid4().hex}{extension}'
        render(source, target, keep, params, info, work_dir=scratch, cancel=cancel,
               limit=PREVIEW_SECONDS)
        return target
    finally:
        for leftover in scratch.glob('*'):
            leftover.unlink(missing_ok=True)
        try:
            scratch.rmdir()
        except OSError:
            pass
