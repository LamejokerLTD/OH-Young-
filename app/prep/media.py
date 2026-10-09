"""FFmpeg probing, cancellable execution and silence detection.

Every external process uses an argument list (never a shell) and runs with
-protocol_whitelist file,pipe so a crafted playlist cannot make FFmpeg read
network or other local resources.
"""
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from app.audio import ffmpeg
from app.prep.errors import PrepCancelled, PrepError

STANDARD_RATES = (
    Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001),
    Fraction(30), Fraction(50), Fraction(60000, 1001), Fraction(60),
)
SAFE_INPUT = ['-nostdin', '-hide_banner', '-protocol_whitelist', 'file,pipe']


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    has_video: bool
    has_audio: bool
    width: int
    height: int
    fps: Fraction
    audio_channels: int
    audio_rate: int
    rotation: int = 0   # display matrix rotation in degrees, as FFmpeg reports it (e.g. -90)


def nearest_rate(value: float) -> Fraction:
    return min(STANDARD_RATES, key=lambda rate: abs(float(rate) - value))


_DURATION = re.compile(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)')
_VIDEO = re.compile(r'Stream #\d+:\d+[^:]*: Video: .*?, (\d{2,5})x(\d{2,5})[ ,\[]')
_TBR = re.compile(r'(\d+(?:\.\d+)?) tbr')
_AUDIO = re.compile(r'Stream #\d+:\d+[^:]*: Audio: .*?, (\d{4,6}) Hz, ([^,]+)')
_ROTATION = re.compile(r'rotation of (-?\d+(?:\.\d+)?) degrees')
_SILENCE = re.compile(r'silence_(start|end): (-?\d+(?:\.\d+)?)')


def run_tool(args, *, log_dir: Path, cancel=None, timeout=4 * 3600):
    """Run FFmpeg, polling for cancellation. Returns (exit_code, stderr_text)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f'ffmpeg-{uuid.uuid4().hex}.log'
    with open(log, 'wb') as handle:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=handle,
        )
        started = time.monotonic()
        while True:
            try:
                code = process.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    process.kill()
                    process.wait()
                    log.unlink(missing_ok=True)
                    raise PrepCancelled()
                if time.monotonic() - started > timeout:
                    process.kill()
                    process.wait()
                    log.unlink(missing_ok=True)
                    raise PrepError('處理時間超過上限，請縮短影片或調整參數後重試。')
    text = log.read_text(encoding='utf-8', errors='replace')
    log.unlink(missing_ok=True)
    return code, text


def probe(source: Path, *, log_dir: Path, cancel=None) -> MediaInfo:
    # FFmpeg exits non-zero without an output; the stream list is on stderr.
    _, text = run_tool([ffmpeg(), *SAFE_INPUT, '-i', str(source)], log_dir=log_dir, cancel=cancel)
    if 'Input #0' not in text:
        raise PrepError('無法讀取這個檔案，可能已損壞或不是支援的媒體格式。')
    duration_match = _DURATION.search(text)
    if not duration_match:
        raise PrepError('無法判斷影片長度。')
    h, m, s = duration_match.groups()
    duration = int(h) * 3600 + int(m) * 60 + float(s)
    audio = _AUDIO.search(text)
    if not audio:
        raise PrepError('這個檔案沒有音軌，無法處理。')
    video = _VIDEO.search(text)
    tbr = _TBR.search(text)
    width, height = (int(video.group(1)), int(video.group(2))) if video else (0, 0)
    rotation = 0
    match = _ROTATION.search(text)
    if match:
        rotation = int(round(float(match.group(1))))
        if abs(abs(rotation) % 180 - 90) < 1:
            # Phone footage stores rotation metadata; the displayed frame is height x width.
            width, height = height, width
    layout = audio.group(2)
    channels = 1 if 'mono' in layout else 2
    if duration <= 0:
        raise PrepError('這個檔案沒有可處理的內容。')
    return MediaInfo(
        duration=duration,
        has_video=bool(video),
        has_audio=True,
        width=width,
        height=height,
        fps=nearest_rate(float(tbr.group(1))) if (video and tbr) else Fraction(0),
        audio_channels=channels,
        audio_rate=int(audio.group(1)),
        rotation=rotation,
    )


def detect_silence(source: Path, *, threshold_db: float, min_silence: float, limit: float | None,
                   duration: float, log_dir: Path, cancel=None) -> list[tuple[float, float]]:
    args = [ffmpeg(), *SAFE_INPUT]
    if limit:
        args += ['-t', f'{limit:.3f}']
    args += [
        '-i', str(source), '-vn',
        '-af', f'silencedetect=noise={threshold_db:.1f}dB:d={min_silence:.2f}',
        '-f', 'null', '-',
    ]
    code, text = run_tool(args, log_dir=log_dir, cancel=cancel)
    if code:
        raise PrepError('靜音偵測失敗，請確認檔案可正常播放。')
    silences = []
    start = None
    for kind, value in _SILENCE.findall(text):
        if kind == 'start':
            start = float(value)
        elif start is not None:
            silences.append((start, float(value)))
            start = None
    if start is not None:
        silences.append((start, duration))
    return silences
