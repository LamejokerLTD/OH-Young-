import json
import os
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.prep import cutlist, store
from app.prep.errors import PrepError
from app.prep.media import MediaInfo
from app.prep.params import Params
from app.prep.paths import list_inputs, resolve_input


@pytest.fixture
def video_root(tmp_path, monkeypatch):
    root = tmp_path / 'Video'
    root.mkdir()
    monkeypatch.setenv('WHISPER_VIDEO_ROOT', str(root))
    return root


def _info(**overrides):
    values = dict(duration=10.0, has_video=True, has_audio=True, width=1920, height=1080,
                  fps=Fraction(24000, 1001), audio_channels=2, audio_rate=48000, rotation=0)
    values.update(overrides)
    return MediaInfo(**values)


# ---------- parameters ----------

def test_params_defaults_render_nothing():
    assert Params().needs_render is False


def test_params_speed_out_of_range_rejected():
    with pytest.raises(ValidationError):
        Params.model_validate({'speed': 2.5})
    with pytest.raises(ValidationError):
        Params.model_validate({'speed': 0.5})


def test_params_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        Params.model_validate({'speed': 1.1, 'output_path': '/etc/passwd'})


def test_params_bad_choice_rejected():
    with pytest.raises(ValidationError):
        Params.model_validate({'clarity': {'denoise': 'extreme'}})
    with pytest.raises(ValidationError):
        Params.model_validate({'transcript': {'language': 'xx'}})


def test_params_any_edit_requires_render():
    assert Params.model_validate({'speed': 1.2}).needs_render
    assert Params.model_validate({'clarity': {'loudness': True}}).needs_render
    assert Params.model_validate({'silence': {'enabled': True}}).needs_render


# ---------- keep segments and cut lists ----------

def test_keep_segments_leave_padding_around_speech():
    keep = cutlist.keep_segments(10.0, [(2.0, 6.0)], pad=0.2)
    assert keep == [(0.0, 2.2), (5.8, 10.0)]


def test_keep_segments_all_silence_is_empty():
    assert cutlist.keep_segments(4.0, [(0.0, 4.0)], pad=0.1) == []


def test_keep_segments_without_silence_is_whole_clip():
    assert cutlist.keep_segments(7.0, [], pad=0.1) == [(0.0, 7.0)]


def test_keep_segments_drops_tiny_fragments():
    keep = cutlist.keep_segments(3.0, [(0.0, 1.0), (1.05, 2.0)], pad=0.0, min_keep=0.1)
    assert all(end - start >= 0.1 for start, end in keep)


def test_timeline_is_frame_accurate_and_contiguous():
    rows = cutlist.timeline([(0.0, 1.0), (2.0, 3.5)], Fraction(24))
    assert rows[0] == {'src_in': 0, 'src_out': 24, 'rec_in': 0, 'rec_out': 24}
    assert rows[1] == {'src_in': 48, 'src_out': 84, 'rec_in': 24, 'rec_out': 60}


def test_edl_timecodes_match_frames():
    text = cutlist.edl('clip', Fraction(25), [(0.0, 2.0), (4.0, 5.0)])
    assert '001  AX       AA/V  C        00:00:00:00 00:00:02:00 00:00:00:00 00:00:02:00' in text
    assert '002  AX       AA/V  C        00:00:04:00 00:00:05:00 00:00:02:00 00:00:03:00' in text


def test_fcpxml_uses_exact_rational_frame_times(tmp_path):
    source = tmp_path / 'clip.mov'
    source.write_bytes(b'')
    info = _info(fps=Fraction(24000, 1001))
    xml = cutlist.fcpxml('clip', source, info, [(0.0, 1.0), (2.0, 3.0)])
    root = ET.fromstring(xml.split('\n', 2)[2])  # drop declaration and DOCTYPE
    assert root.find('resources/format').get('frameDuration') == '1001/24000s'
    clips = root.findall('.//asset-clip')
    assert len(clips) == 2
    # 24 frames at 24000/1001 fps = 1001/1000 s exactly, not a rounded decimal.
    assert clips[1].get('offset') == '1001/1000s'


def test_premiere_xml_has_one_clip_per_segment_and_audio_tracks(tmp_path):
    source = tmp_path / 'clip.mov'
    source.write_bytes(b'')
    xml = cutlist.premiere('clip', source, _info(), [(0.0, 1.0), (2.0, 3.0), (5.0, 6.0)])
    root = ET.fromstring(xml)
    video_clips = root.findall('./sequence/media/video/track/clipitem')
    assert len(video_clips) == 3
    assert len(root.findall('./sequence/media/audio/track')) == 2
    first = video_clips[0].find('file')
    assert first.find('pathurl').text.startswith('file://localhost/')
    assert video_clips[2].find('start').text == '48'


def test_premiere_audio_only_still_defines_the_file(tmp_path):
    source = tmp_path / 'voice.m4a'
    source.write_bytes(b'')
    info = _info(has_video=False, width=0, height=0, fps=Fraction(0), audio_channels=1)
    root = ET.fromstring(cutlist.premiere('voice', source, info, [(0.0, 1.0)]))
    assert root.findall('./sequence/media/video') == []
    track = root.find('./sequence/media/audio/track/clipitem')
    assert track.find('file').find('name') is not None


def test_xml_escapes_names(tmp_path):
    source = tmp_path / 'a & b.mov'
    source.write_bytes(b'')
    xml = cutlist.premiere('a & <b>', source, _info(), [(0.0, 1.0)])
    ET.fromstring(xml)  # must still parse


# ---------- paths ----------

def test_resolve_accepts_media_inside_video_root(video_root):
    target = video_root / 'a.mp4'
    target.write_bytes(b'x')
    assert resolve_input('a.mp4', video_root) == target.resolve()


@pytest.mark.parametrize('name', ['../secret.mp4', '/etc/passwd.mp4', 'C:/Windows/x.mp4', 'a\x00.mp4', ''])
def test_resolve_rejects_escape_attempts(video_root, name):
    with pytest.raises(PrepError):
        resolve_input(name, video_root)


def test_resolve_rejects_projects_folder(video_root):
    (video_root / 'projects').mkdir()
    (video_root / 'projects' / 'x.mp4').write_bytes(b'x')
    with pytest.raises(PrepError):
        resolve_input('projects/x.mp4', video_root)


def test_resolve_rejects_wrong_extension_and_missing(video_root):
    (video_root / 'notes.txt').write_text('x', encoding='utf-8')
    with pytest.raises(PrepError):
        resolve_input('notes.txt', video_root)
    with pytest.raises(PrepError):
        resolve_input('missing.mp4', video_root)


def test_list_inputs_skips_projects_and_unsupported_files(video_root):
    (video_root / 'a.mp4').write_bytes(b'x')
    (video_root / 'sub').mkdir()
    (video_root / 'sub' / 'b.wav').write_bytes(b'x')
    (video_root / 'readme.md').write_text('x', encoding='utf-8')
    (video_root / 'projects').mkdir()
    (video_root / 'projects' / 'c.mp4').write_bytes(b'x')
    paths = [item['path'] for item in list_inputs(video_root)]
    assert paths == ['a.mp4', 'sub/b.wav']


# ---------- store ----------

def test_store_roundtrip_and_interrupted_marking(video_root):
    manifest = store.create('a.mp4', 'a', {'speed': 1.0}, root=video_root)
    assert store.load(manifest['id'], video_root)['status'] == 'queued'
    assert store.mark_interrupted(video_root) == 1
    loaded = store.load(manifest['id'], video_root)
    assert loaded['status'] == 'failed'
    assert '重新啟動' in loaded['error']


def test_intermediates_expire_but_outputs_stay(video_root):
    manifest = store.create('a.mp4', 'a', {}, root=video_root)
    folder = store.project_dir(manifest['id'], video_root)
    (folder / 'intermediate' / 'scratch.wav').write_bytes(b'x')
    (folder / 'output' / 'cutlist.edl').write_text('x', encoding='utf-8')
    manifest['status'] = 'done'
    store.save(manifest, video_root)
    future = time.time() + 8 * 86400
    assert store.cleanup_intermediates(video_root, now=future) == 1
    assert not (folder / 'intermediate' / 'scratch.wav').exists()
    assert (folder / 'output' / 'cutlist.edl').exists()


def test_active_projects_are_not_cleaned(video_root):
    manifest = store.create('a.mp4', 'a', {}, root=video_root)
    folder = store.project_dir(manifest['id'], video_root)
    (folder / 'intermediate' / 'busy.wav').write_bytes(b'x')
    assert store.cleanup_intermediates(video_root, now=time.time() + 8 * 86400) == 0
    assert (folder / 'intermediate' / 'busy.wav').exists()


def test_delete_outputs_refuses_active_job(video_root):
    manifest = store.create('a.mp4', 'a', {}, root=video_root)
    with pytest.raises(PrepError):
        store.delete_outputs(manifest['id'], video_root)


def test_project_id_must_be_hex(video_root):
    with pytest.raises(PrepError):
        store.load('../../etc', video_root)


def test_stale_sessions_removed_but_live_session_kept(tmp_path):
    from app.cleanup import purge_stale_sessions
    live = tmp_path / ('session-' + 'a' * 32)
    old = tmp_path / ('session-' + 'b' * 32)
    other = tmp_path / 'pytest-of-jedia'
    for directory in (live, old, other):
        directory.mkdir()
    past = time.time() - 3 * 86400
    os.utime(old, (past, past))
    os.utime(other, (past, past))
    assert purge_stale_sessions(tmp_path, keep=live) == 1
    assert live.exists() and not old.exists() and other.exists()


# ---------- queue ----------

def test_queue_runs_jobs_in_order_and_supports_cancel(video_root, monkeypatch):
    from app.prep import pipeline
    from app.prep.queue import BatchQueue

    started = []
    release = threading.Event()

    def fake_run(manifest, provider, cancel, root=None):
        started.append(manifest['name'])
        if manifest['name'] == 'first':
            release.wait(5)
        if cancel.is_set():
            from app.prep.errors import PrepCancelled
            raise PrepCancelled()

    monkeypatch.setattr(pipeline, 'run', fake_run)
    queue = BatchQueue(video_root, provider_factory=lambda: None)
    first = store.create('first.mp4', 'first', {}, root=video_root)
    second = store.create('second.mp4', 'second', {}, root=video_root)
    queue.submit(first['id'])
    queue.submit(second['id'])
    assert queue.cancel(second['id']) == 'cancelled'
    release.set()

    deadline = time.time() + 5
    while time.time() < deadline:
        if store.load(first['id'], video_root)['status'] == 'done':
            break
        time.sleep(0.05)
    assert store.load(first['id'], video_root)['status'] == 'done'
    assert store.load(second['id'], video_root)['status'] == 'cancelled'
    assert started == ['first']


def test_queue_reports_pipeline_errors_to_the_project(video_root, monkeypatch):
    from app.prep import pipeline
    from app.prep.queue import BatchQueue

    def broken(manifest, provider, cancel, root=None):
        raise PrepError('這個檔案沒有音軌，無法處理。')

    monkeypatch.setattr(pipeline, 'run', broken)
    queue = BatchQueue(video_root, provider_factory=lambda: None)
    manifest = store.create('x.mp4', 'x', {}, root=video_root)
    queue.submit(manifest['id'])
    deadline = time.time() + 5
    while time.time() < deadline and store.load(manifest['id'], video_root)['status'] != 'failed':
        time.sleep(0.05)
    loaded = store.load(manifest['id'], video_root)
    assert loaded['status'] == 'failed'
    assert loaded['error'] == '這個檔案沒有音軌，無法處理。'


# ---------- real FFmpeg, small generated media ----------

def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


@pytest.mark.skipif(not shutil.which('ffmpeg') and not Path(_ffmpeg()).exists(), reason='FFmpeg unavailable')
def test_render_removes_silence_and_matches_expected_length(video_root, tmp_path):
    from app.prep.media import detect_silence, probe
    from app.prep.render import render

    source = video_root / 'tone.mp4'
    # 2 s tone, 2 s silence, 2 s tone, 320x240 video.
    subprocess.run([
        _ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=24:duration=6',
        '-f', 'lavfi', '-i', 'aevalsrc=if(lt(mod(t\\,6)\\,2)+gte(mod(t\\,6)\\,4)\\,0.4*sin(2*PI*440*t)\\,0):s=48000:d=6',
        '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source),
    ], check=True, timeout=120)

    work = tmp_path / 'work'
    info = probe(source, log_dir=work)
    silences = detect_silence(source, threshold_db=-35, min_silence=0.8, limit=None,
                              duration=info.duration, log_dir=work)
    keep = cutlist.keep_segments(info.duration, silences, pad=0.1)
    expected = sum(end - start for start, end in keep)
    assert 2.0 < expected < 4.6  # one 2 s silence, pads leave it slightly shorter than the 4 s of speech

    params = Params.model_validate({'silence': {'enabled': True, 'pad': 0.1}, 'speed': 1.25,
                                    'clarity': {'loudness': True}})
    output = tmp_path / 'render.mp4'
    render(source, output, keep, params, info, work_dir=work)
    rendered = probe(output, log_dir=work)
    assert abs(rendered.duration - expected / 1.25) < 0.3
    assert rendered.width == info.width and rendered.height == info.height


def _flash_time(path):
    """First frame whose average brightness jumps: the white flash."""
    import re
    result = subprocess.run([
        _ffmpeg(), '-hide_banner', '-i', str(path), '-an',
        '-vf', 'signalstats,metadata=print:key=lavfi.signalstats.YAVG', '-f', 'null', '-',
    ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    times = re.findall(r'pts_time:([\d.]+)\s*\n.*?YAVG=([\d.]+)', result.stderr)
    return next(float(t) for t, y in times if float(y) > 100)


def _beep_time(path):
    import re
    result = subprocess.run([
        _ffmpeg(), '-hide_banner', '-i', str(path), '-vn',
        '-af', 'silencedetect=noise=-30dB:d=0.05', '-f', 'null', '-',
    ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    return float(re.findall(r'silence_end: ([\d.]+)', result.stderr)[0])


@pytest.mark.parametrize('speed', [1.0, 1.25])
def test_render_keeps_audio_in_sync_when_audio_track_starts_late(video_root, tmp_path, speed):
    """Phone footage: audio track starts after the video. Flash and beep must stay aligned after cuts."""
    from app.prep.media import probe
    from app.prep.render import render

    work = tmp_path / 'work'
    work.mkdir()
    video = work / 'v.mp4'
    audio = work / 'a.wav'
    subprocess.run([
        _ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
        '-i', 'color=c=black:s=320x240:r=30:d=4',
        '-vf', "drawbox=enable='between(t,2,2.2)':color=white:t=fill",
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video),
    ], check=True, timeout=120)
    # Audio track begins 0.4 s late, so the beep at local 1.6 s plays at 2.0 s with the flash.
    subprocess.run([
        _ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
        '-i', r'aevalsrc=if(between(t\,1.6\,1.8)\,0.5*sin(2*PI*1000*t)\,0):s=48000:d=3.6',
        str(audio),
    ], check=True, timeout=120)
    source = video_root / 'phone.mov'
    subprocess.run([
        _ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(video),
        '-itsoffset', '0.4', '-i', str(audio), '-map', '0:v', '-map', '1:a',
        '-c:v', 'copy', '-c:a', 'pcm_s16le', str(source),
    ], check=True, timeout=120)
    assert abs(_flash_time(source) - _beep_time(source)) < 0.05  # the source itself is in sync

    info = probe(source, log_dir=work)
    keep = [(0.0, 1.0), (1.5, 4.0)]
    params = Params.model_validate({'silence': {'enabled': True}, 'speed': speed})
    output = tmp_path / 'render.mp4'
    render(source, output, keep, params, info, work_dir=work)

    flash, beep = _flash_time(output), _beep_time(output)
    assert abs(flash - 1.5 / speed) < 0.08
    assert abs(flash - beep) < 0.05


def test_align_shifts_audio_from_the_original_render_and_moves_subtitles(video_root, tmp_path):
    from app.prep import pipeline

    manifest = store.create('clip.mp4', 'clip', {}, root=video_root)
    output = store.project_dir(manifest['id'], video_root) / 'output'
    render_file = output / 'render.mp4'
    subprocess.run([
        _ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', 'color=c=black:s=320x240:r=30:d=4',
        '-f', 'lavfi', '-i', r'aevalsrc=if(between(t\,2\,2.2)\,0.5*sin(2*PI*1000*t)\,0):s=48000:d=4',
        '-vf', "drawbox=enable='between(t,2,2.2)':color=white:t=fill",
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(render_file),
    ], check=True, timeout=120)
    transcript = output / 'transcript'
    transcript.mkdir()
    result = {'segments': [{'start': 2.0, 'end': 2.2, 'text': '嗶', 'words': [{'start': 2.0, 'end': 2.2}]}],
              'subtitles': [{'start': 2.0, 'end': 2.2, 'text': '嗶'}]}
    (transcript / 'transcript.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    manifest['status'] = 'done'
    store.save(manifest, video_root)

    pipeline.align(manifest, 300, video_root)
    assert abs((_beep_time(render_file) - _flash_time(render_file)) - 0.3) < 0.05
    saved = json.loads((transcript / 'transcript.json').read_text(encoding='utf-8'))
    assert saved['subtitles'][0]['start'] == pytest.approx(2.3)
    assert saved['segments'][0]['words'][0]['start'] == pytest.approx(2.3)
    assert '00:00:02,300' in (transcript / 'transcript.srt').read_text(encoding='utf-8')

    # The next adjustment starts again from the original render, so offsets never stack.
    pipeline.align(manifest, -200, video_root)
    assert abs((_beep_time(render_file) - _flash_time(render_file)) + 0.2) < 0.05
    saved = json.loads((transcript / 'transcript.json').read_text(encoding='utf-8'))
    assert saved['subtitles'][0]['start'] == pytest.approx(1.8)
    assert store.load(manifest['id'], video_root)['av_offset_ms'] == -200
    assert '.render-base.mp4' not in [path.name for path in store.output_files(manifest, video_root).values()]


def test_align_refuses_unfinished_jobs_and_out_of_range_offsets(video_root):
    from app.prep import pipeline

    manifest = store.create('clip.mp4', 'clip', {}, root=video_root)
    with pytest.raises(PrepError):
        pipeline.align(manifest, 100, video_root)
    manifest['status'] = 'done'
    with pytest.raises(PrepError):
        pipeline.align(manifest, 5000, video_root)
    with pytest.raises(PrepError):
        pipeline.align(manifest, 100, video_root)   # no render.mp4
