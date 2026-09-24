import os
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('WHISPER_DATA', ROOT)).resolve()
for name in ('uploads', 'outputs', 'temp', 'logs', 'models'):
    (DATA / name).mkdir(parents=True, exist_ok=True)
os.environ.setdefault('HF_HOME', str(DATA/'models'/'huggingface'))
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '60')
WORK = DATA/'temp'/('session-' + uuid.uuid4().hex)
for name in ('uploads', 'outputs', 'temp'):
    (WORK/name).mkdir(parents=True, exist_ok=True)
EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.mp3', '.wav', '.m4a', '.aac', '.flac', '.webm'}
MAX_UPLOAD = 30 * 1024**3
DLL_HANDLES = []

def prepare_cuda():
    import site
    if os.name == 'nt':
        for root in site.getsitepackages():
            for directory in Path(root).glob('nvidia/*/bin'):
                os.environ['PATH'] = str(directory) + os.pathsep + os.environ.get('PATH', '')
                DLL_HANDLES.append(os.add_dll_directory(str(directory)))

prepare_cuda()
