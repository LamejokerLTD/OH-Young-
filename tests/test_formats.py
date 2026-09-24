import subprocess
import pytest
from app.audio import ffmpeg,extract,MediaError

@pytest.mark.parametrize('extension', ['mp4','mov','mkv','avi','mp3','wav','m4a','aac','flac','webm'])
def test_supported_containers(tmp_path,extension):
    source=tmp_path/f'fixture.{extension}'
    subprocess.run([ffmpeg(),'-nostdin','-hide_banner','-loglevel','error','-f','lavfi',
                    '-i','sine=frequency=440:duration=0.5',str(source)],check=True,capture_output=True)
    assert extract(source,tmp_path/'out.wav')>.4

def test_video_without_audio(tmp_path):
    source=tmp_path/'silent.mp4'
    subprocess.run([ffmpeg(),'-nostdin','-hide_banner','-loglevel','error','-f','lavfi',
                    '-i','color=size=64x64:duration=0.5','-an',str(source)],check=True,capture_output=True)
    with pytest.raises(MediaError):extract(source,tmp_path/'out.wav')
