import shutil
import subprocess
import wave
from pathlib import Path

class MediaError(Exception):
    pass

def ffmpeg():
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise MediaError('找不到 FFmpeg，請重新執行 install.bat。') from exc

def extract(source: Path, target: Path):
    # Local file only. Disallow nested network/file references in malicious playlists.
    args = [ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
            '-protocol_whitelist', 'file,pipe', '-format_whitelist',
            'mov,matroska,webm,avi,mp3,wav,aac,flac', '-i', str(source),
            '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(target)]
    result = subprocess.run(args, capture_output=True, timeout=4*3600)
    if result.returncode:
        detail = result.stderr.decode('utf-8', errors='replace')
        if 'space' in detail.lower():
            raise MediaError('磁碟空間不足，請釋放空間後重試。')
        raise MediaError('無法讀取音軌：檔案可能損壞、沒有音訊，或不是支援的媒體容器。')
    with wave.open(str(target), 'rb') as wav:
        duration = wav.getnframes() / wav.getframerate()
    if duration <= 0:
        raise MediaError('這個檔案沒有可辨識的音訊。')
    return duration

def chunks(path, seconds=300):
    """Bound decoded audio to five minutes; offsets remain original media time."""
    import numpy as np
    with wave.open(str(path), 'rb') as wav:
        rate = wav.getframerate()
        offset = 0
        while data := wav.readframes(rate * seconds):
            audio = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768
            if len(audio) == rate * seconds and seconds >= 30:
                # Prefer a quiet 100 ms boundary in the last ten seconds.
                width = rate // 10
                begin = len(audio) - rate * 10
                energies = [(float(np.mean(audio[i:i+width] ** 2)), i+width//2)
                            for i in range(begin, len(audio)-width, width)]
                energy, boundary = min(energies)
                if energy < .0001:
                    audio = audio[:boundary]
                    wav.setpos(offset + boundary)
            yield offset / rate, audio
            offset += len(audio)

def preview_audio(source, target):
    subprocess.run([ffmpeg(), '-nostdin','-hide_banner','-loglevel','error','-y',
                    '-i',str(source),'-c:a','libmp3lame','-b:a','96k',str(target)],
                   capture_output=True, check=True, timeout=4*3600)
