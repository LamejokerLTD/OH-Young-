import os
import tempfile
import pytest
os.environ['WHISPER_DATA']=tempfile.mkdtemp(prefix='whisper-test-')
from fastapi.testclient import TestClient
from app.main import app, manager
from app.config import WORK as DATA
from app.subtitle import export
client=TestClient(app)
headers={'X-Local-Request':'1','Content-Type':'audio/wav'}

@pytest.fixture(autouse=True)
def reset_manager_state():
    """Keep API tests independent from queued jobs created by earlier tests."""
    manager.jobs.clear()
    yield
    manager.jobs.clear()

def test_home_and_security():
    assert client.get('/').status_code==200
    assert client.get('/api/jobs/../../secret').status_code==404
    assert client.post('/api/jobs?filename=a.wav',content=b'1').status_code==403
    assert client.post('/api/jobs?filename=a.exe',headers=headers,content=b'1').status_code==415
    assert client.post('/api/jobs?filename=a.wav',headers=headers,content=b'').status_code==400
    assert client.post('/api/jobs?filename=a.wav',headers={**headers,'Origin':'https://evil.example'},content=b'1').status_code==403

def test_upload_status_download(monkeypatch):
    monkeypatch.setattr(manager.pool,'submit',lambda *a:None)
    response=client.post('/api/jobs',params={'filename':'../../unsafe.wav'},headers=headers,content=b'test')
    assert response.status_code==202
    id=response.json()['id']
    assert (DATA/'uploads'/id).read_bytes()==b'test'
    assert client.get('/api/jobs/'+id).json()['file']=='unsafe.wav'
    assert client.get('/api/jobs/'+id+'/download/json').status_code==409
    export({'subtitles':[],'segments':[]},DATA/'outputs'/id)
    manager.update(id,status='done')
    for f in ('json','srt','vtt','txt','timed.txt'):
        assert client.get('/api/jobs/'+id+'/download/'+f).status_code==200
    assert client.get('/api/jobs/'+id+'/download/status.json').status_code==404
    assert client.get('/api/jobs/'+id+'/media',headers={'Range':'bytes=0-1'}).status_code==206
    assert client.delete('/api/jobs/'+id,headers=headers).status_code==200

def test_invalid_media_is_readable_job_error(monkeypatch):
    monkeypatch.setattr(manager.pool,'submit',lambda *a:None)
    response=client.post('/api/jobs?filename=fake.wav',headers=headers,content=b'not real audio')
    id=response.json()['id']
    manager.run(id,'zh',True,'standard')
    status=client.get('/api/jobs/'+id).json()
    assert status['status']=='error'
    assert '音軌' in status['stage']
    assert 'Traceback' not in status['stage']
    assert not (DATA/'temp'/f'{id}.wav').exists()

def test_size_limit_cleans_partial_upload(monkeypatch):
    import app.main as module
    monkeypatch.setattr(module,'MAX_UPLOAD',2)
    before=set((DATA/'uploads').iterdir())
    assert client.post('/api/jobs?filename=big.wav',headers=headers,content=b'123').status_code==413
    assert set((DATA/'uploads').iterdir())==before

def test_next_job_clears_previous_result(monkeypatch):
    monkeypatch.setattr(manager.pool,'submit',lambda *a:None)
    first=client.post('/api/jobs?filename=first.wav',headers=headers,content=b'first').json()['id']
    export({'subtitles':[],'segments':[]}, DATA/'outputs'/first)
    manager.update(first,status='done')
    assert client.get(f'/api/jobs/{first}/download/txt').status_code==200
    assert client.post('/api/jobs?filename=bad.exe',headers=headers,content=b'bad').status_code==415
    assert client.get(f'/api/jobs/{first}/download/txt').status_code==200
    second=client.post('/api/jobs?filename=second.wav',headers=headers,content=b'second').json()['id']
    assert not (DATA/'uploads'/first).exists()
    assert not (DATA/'outputs'/first).exists()
    assert client.get(f'/api/jobs/{first}').status_code==404
    assert client.post('/api/jobs?filename=third.wav',headers=headers,content=b'third').status_code==409
    assert (DATA/'uploads'/second).read_bytes()==b'second'
    assert not list(DATA.glob('outputs/*/status.json'))
    manager.update(second,status='error')
    manager.delete(second)


def test_session_cleanup_preserves_models(tmp_path):
    from app.cleanup import remove_session
    import pytest
    session=tmp_path/'temp'/('session-'+'a'*32)
    session.mkdir(parents=True)
    (session/'result.txt').write_text('private')
    model=tmp_path/'models'/'model.bin'
    model.parent.mkdir(); model.write_bytes(b'cached')
    remove_session(session)
    assert not session.exists()
    assert model.read_bytes()==b'cached'
    with pytest.raises(ValueError): remove_session(model.parent)


def test_watcher_cleans_after_process_exit(tmp_path):
    import subprocess, sys, time
    import pytest
    if os.name!='nt': pytest.skip('Windows cleanup watcher')
    session=tmp_path/'temp'/('session-'+'b'*32)
    session.mkdir(parents=True)
    (session/'private.txt').write_text('temporary')
    code="from app.cleanup import start_watcher; import sys,time; start_watcher(sys.argv[1]); print('ready',flush=True); time.sleep(30)"
    child=subprocess.Popen([sys.executable,'-c',code,str(session)],stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='ready'
        time.sleep(1)
        child.terminate(); child.wait(timeout=5)
        deadline=time.monotonic()+10
        while session.exists() and time.monotonic()<deadline: time.sleep(.1)
        assert not session.exists()
    finally:
        if child.poll() is None: child.kill(); child.wait()
