import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.prep import queue as queue_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / 'Video'
    root.mkdir()
    (root / 'clip.mp4').write_bytes(b'not really media')
    monkeypatch.setenv('WHISPER_VIDEO_ROOT', str(root))
    # Never start the real worker (it would load the GPU model) during API tests.
    monkeypatch.setattr(queue_module, '_queue', None)

    class Idle:
        def submit(self, pid):
            pass

    monkeypatch.setattr(queue_module, 'get_queue', lambda: Idle())
    monkeypatch.setattr('app.prep.routes.get_queue', lambda: Idle())
    return TestClient(app)


LOCAL = {'X-Local-Request': '1'}


def test_prep_page_is_served(client):
    response = client.get('/prep')
    assert response.status_code == 200
    assert 'prep.js' in response.text


def test_inputs_lists_only_media(client):
    body = client.get('/api/prep/inputs').json()
    assert [item['path'] for item in body['items']] == ['clip.mp4']


def test_batch_rejects_path_escape(client):
    response = client.post('/api/prep/batches', json={'inputs': ['../../secret.mp4']}, headers=LOCAL)
    assert response.status_code == 400


def test_batch_rejects_unknown_parameters(client):
    response = client.post('/api/prep/batches',
                           json={'inputs': ['clip.mp4'], 'params': {'speed': 1.0, 'shell': 'rm -rf'}},
                           headers=LOCAL)
    assert response.status_code == 422


def test_batch_rejects_out_of_range_speed(client):
    response = client.post('/api/prep/batches',
                           json={'inputs': ['clip.mp4'], 'params': {'speed': 9}}, headers=LOCAL)
    assert response.status_code == 422


def test_writes_require_local_header(client):
    response = client.post('/api/prep/batches', json={'inputs': ['clip.mp4']})
    assert response.status_code == 403


def test_writes_from_foreign_origin_are_refused(client):
    response = client.post('/api/prep/batches', json={'inputs': ['clip.mp4']},
                           headers={'X-Local-Request': '1', 'Origin': 'https://evil.example'})
    assert response.status_code == 403


def test_unknown_download_kind_is_not_found(client):
    response = client.get('/api/prep/projects/' + 'a' * 32 + '/files/../../etc')
    assert response.status_code in (404, 400)
    response = client.get('/api/prep/projects/' + 'a' * 32 + '/files/passwords')
    assert response.status_code in (404, 400)


def test_preview_name_must_match_pattern(client):
    assert client.get('/api/prep/previews/..%2Fsecret.mp4').status_code == 404
    assert client.get('/api/prep/previews/' + 'b' * 32 + '.mp4').status_code == 404


def test_malformed_project_id_is_refused(client):
    response = client.get('/api/prep/projects/..%5C..%5Cetc')
    assert response.status_code in (400, 404)


def test_align_rejects_out_of_range_offset(client):
    response = client.post('/api/prep/projects/' + 'a' * 32 + '/align', json={'offset_ms': 99999}, headers=LOCAL)
    assert response.status_code == 422


def test_align_requires_local_header(client):
    response = client.post('/api/prep/projects/' + 'a' * 32 + '/align', json={'offset_ms': 100})
    assert response.status_code == 403
