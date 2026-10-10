import os
import tempfile

# Tests must never touch the real Video folder: the app's startup marks unfinished jobs
# there as interrupted, which would corrupt the state of a job the user is running.
os.environ['WHISPER_VIDEO_ROOT'] = tempfile.mkdtemp(prefix='whisper-video-test-')
