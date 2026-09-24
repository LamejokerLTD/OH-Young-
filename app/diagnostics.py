import ctypes
import json
import os
import subprocess
from app.config import DATA
from app.audio import ffmpeg
from app.transcriber import gpu_status

def check():
    import faster_whisper
    from app.pipeline_a import SpeechEnhancer
    subprocess.run([ffmpeg(),'-version'], check=True, capture_output=True)
    status = gpu_status()
    print(json.dumps(status,ensure_ascii=True,indent=2))
    if os.name == 'nt' and status['cuda']:
        try:
            ctypes.WinDLL('cublas64_12.dll')
            ctypes.WinDLL('cudnn64_9.dll')
            print('CUDA runtime libraries loaded. Real model inference is verified on first transcription.')
        except OSError as exc:
            print('WARNING: CUDA DLL load failed; CPU fallback will be used:',exc)
    else:
        print('WARNING: CUDA not available; CPU fallback will be used.')
    print('FFmpeg, faster-whisper, and speech enhancement imports OK.')
    print('Model cache:', DATA/'models')

if __name__=='__main__':
    check()
