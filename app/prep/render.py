"""Build and run the FFmpeg render: silence cuts, clarity chain, pitch-preserving speed, H.264 encode.

The filter graph is written to a script file, so long cut lists never hit the
Windows command-line length limit.
"""
import logging
import subprocess
from pathlib import Path

from app.audio import ffmpeg
from app.prep.errors import PrepError
from app.prep.media import SAFE_INPUT, MediaInfo, run_tool
from app.prep.params import Clarity, Params

logger = logging.getLogger(__name__)

DENOISE = {
    'light': 'afftdn=nr=10:nf=-35',
    'strong': 'afftdn=nr=20:nf=-30:nt=w',
}
EQ = 'highpass=f=80,equalizer=f=250:t=q:w=1:g=-1.5,equalizer=f=3000:t=q:w=1.2:g=2'
BALANCE = 'acompressor=threshold=-18dB:ratio=3:attack=10:release=150:makeup=2'
LOUDNESS = 'loudnorm=I=-16:TP=-1.5:LRA=11'

_encoder_cache = {}


def clarity_filters(clarity: Clarity) -> list[str]:
    chain = []
    if clarity.denoise != 'off':
        chain.append(DENOISE[clarity.denoise])
    if clarity.eq:
        chain.append(EQ)
    if clarity.balance:
        chain.append(BALANCE)
    if clarity.loudness:
        chain.append(LOUDNESS)
    return chain


def _between(keep) -> str:
    return '+'.join(f'between(t,{start:.3f},{end:.3f})' for start, end in keep)


def _rotation_filters(rotation: int) -> list[str]:
    """Upright the frame. The input display rotation is zeroed in render(), so this is the only turn."""
    turns = rotation % 360
    if turns == 90:
        return ['transpose=cclock']
    if turns == 270:
        return ['transpose=clock']
    if turns == 180:
        return ['hflip,vflip']
    return []


def filter_graph(keep, params: Params, info: MediaInfo, cut: bool) -> str:
    """Return the filter_complex text. `cut` is False when silence removal is off."""
    parts = []
    if info.has_video:
        video = _rotation_filters(info.rotation)
        if cut:
            video += [f"select='{_between(keep)}'", 'setpts=N/FRAME_RATE/TB']
        if params.speed != 1.0:
            video.append(f'setpts=PTS/{params.speed:.4f}')
        if cut or params.speed != 1.0:
            # Constant frame rate after retiming: NVENC rejects the irregular timestamps otherwise.
            video.append(f'fps={info.fps.numerator}/{info.fps.denominator}')
        parts.append(f"[0:v:0]{','.join(video) or 'null'}[vout]")
    audio = []
    if cut:
        audio += [f"aselect='{_between(keep)}'", 'asetpts=N/SR/TB']
    audio += clarity_filters(params.clarity)
    if params.speed != 1.0:
        audio.append(f'atempo={params.speed:.4f}')
    parts.append(f"[0:a:0]{','.join(audio) or 'anull'}[aout]")
    return ';\n'.join(parts) + '\n'


def _video_encoder(log_dir: Path) -> str:
    """Prefer NVENC when this FFmpeg build has it; otherwise software x264."""
    key = 'nvenc'
    if key not in _encoder_cache:
        listing = subprocess.run(
            [ffmpeg(), '-hide_banner', '-encoders'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
        ).stdout
        _encoder_cache[key] = 'h264_nvenc' in listing
    return 'h264_nvenc' if _encoder_cache[key] else 'libx264'


def _encode_args(encoder: str, has_video: bool) -> list[str]:
    if not has_video:
        return ['-vn', '-c:a', 'aac', '-b:a', '192k', '-ac', '2', '-ar', '48000']
    if encoder == 'h264_nvenc':
        video = ['-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '19', '-b:v', '0']
    else:
        video = ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18']
    return [*video, '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k', '-ac', '2', '-ar', '48000',
            '-movflags', '+faststart']


def render(source: Path, output: Path, keep, params: Params, info: MediaInfo, *,
           work_dir: Path, cancel=None, limit: float | None = None) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    cut = params.silence.enabled
    graph = filter_graph(keep, params, info, cut)
    script = work_dir / 'filter-graph.txt'
    script.write_text(graph, encoding='utf-8')

    def build(encoder):
        args = [ffmpeg(), *SAFE_INPUT, '-y']
        if info.rotation:
            # Zero the display matrix on input so the output carries no rotation flag; players would
            # otherwise rotate the already-upright frames a second time.
            args += ['-display_rotation:v:0', '0']
        if limit:
            args += ['-t', f'{limit:.3f}']
        args += ['-i', str(source), '-filter_complex_script', str(script)]
        if info.has_video:
            args += ['-map', '[vout]', '-map', '[aout]']
        else:
            args += ['-map', '[aout]']
        args += _encode_args(encoder, info.has_video)
        args.append(str(output))
        return args

    encoder = _video_encoder(work_dir) if info.has_video else 'none'
    code, text = run_tool(build(encoder), log_dir=work_dir, cancel=cancel)
    if code and encoder == 'h264_nvenc':
        # NVENC can fail on drivers or GPUs without the needed session support; retry on CPU.
        logger.warning('NVENC encode failed, retrying with libx264: %s', text[-400:])
        _encoder_cache['nvenc'] = False
        code, text = run_tool(build('libx264'), log_dir=work_dir, cancel=cancel)
    if code or not output.is_file() or output.stat().st_size == 0:
        logger.error('Render failed: %s', text[-800:])
        raise PrepError('影片處理失敗，請確認檔案可正常播放後重試。')
