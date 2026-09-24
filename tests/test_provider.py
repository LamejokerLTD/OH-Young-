from types import SimpleNamespace
import numpy as np
from app.transcriber import FasterWhisperProvider
import app.transcriber as module

def test_cuda_failure_restarts_cpu(monkeypatch):
    p=FasterWhisperProvider(); devices=[]; updates=[]
    def load(device,update):
        devices.append(device)
        if device=='cuda':raise RuntimeError('CUDA out of memory')
        p.model=SimpleNamespace(transcribe=lambda *a,**kw:(iter([]),SimpleNamespace(duration_after_vad=0,language='zh',language_probability=1)))
    monkeypatch.setattr(p,'load',load)
    monkeypatch.setattr(module,'chunks',lambda path:iter([(0,[0]*16000)]))
    segments,lang,prob,device=p.transcribe(None,'zh',lambda **v:updates.append(v))
    assert devices==['cuda','cpu'] and device=='cpu'
    assert any('CPU' in (u.get('warning') or '') for u in updates)

def test_model_download_error_not_disguised_as_cpu_fallback(monkeypatch):
    import pytest
    p=FasterWhisperProvider()
    monkeypatch.setattr(p,'load',lambda *a:(_ for _ in ()).throw(ConnectionError('download unavailable')))
    with pytest.raises(ConnectionError):p.transcribe(None,'zh',lambda **v:None)

def test_audible_empty_chunk_is_recovered_with_original_timestamps(monkeypatch):
    p=FasterWhisperProvider(); calls=[]
    empty=SimpleNamespace(duration_after_vad=1,language='zh',language_probability=1)
    word=SimpleNamespace(word='重試',start=1.5,end=3,probability=.9)
    recovered=SimpleNamespace(text=' 重試',start=1.5,end=3,words=[word])
    def transcribe(audio, **kwargs):
        calls.append(len(audio))
        return (iter([]),empty) if len(calls)==1 else (iter([recovered]),empty)
    p.model=SimpleNamespace(transcribe=transcribe); p.device='cpu'
    monkeypatch.setattr(p,'load',lambda *args:None)
    monkeypatch.setattr(module,'chunks',lambda path:iter([(10,np.ones(64000,dtype=np.float32)*.1)]))
    segments,*_=p.transcribe(None,'zh',lambda **v:None)
    assert calls==[64000,96000] and segments[0]['start']==11 and segments[0]['end']==12
    assert p.last_recovery['attempted']==1 and p.last_recovery['replaced']==1

def test_blank_recovery_keeps_low_confidence_original(monkeypatch):
    p=FasterWhisperProvider(); info=SimpleNamespace(duration_after_vad=1,language='zh',language_probability=1)
    low=SimpleNamespace(text=' 原文',start=0,end=1,words=[SimpleNamespace(word='原文',start=0,end=1,probability=.1)])
    calls=[]
    def transcribe(audio, **kwargs):
        calls.append(1); return (iter([low]),info) if len(calls)==1 else (iter([]),info)
    p.model=SimpleNamespace(transcribe=transcribe); p.device='cpu'
    monkeypatch.setattr(p,'load',lambda *args:None)
    monkeypatch.setattr(module,'chunks',lambda path:iter([(0,np.ones(16000,dtype=np.float32)*.1)]))
    segments,*_=p.transcribe(None,'zh',lambda **v:None)
    assert len(calls)==2 and segments[0]['text']==' 原文' and p.last_recovery['replaced']==0

def test_silent_empty_chunk_is_not_recovered(monkeypatch):
    p=FasterWhisperProvider(); info=SimpleNamespace(duration_after_vad=0,language='zh',language_probability=1); calls=[]
    def transcribe(*args, **kwargs):
        calls.append(1)
        return iter([]), info
    p.model=SimpleNamespace(transcribe=transcribe); p.device='cpu'
    monkeypatch.setattr(p,'load',lambda *args:None)
    monkeypatch.setattr(module,'chunks',lambda path:iter([(0,np.zeros(16000,dtype=np.float32))]))
    p.transcribe(None,'zh',lambda **v:None)
    assert len(calls)==1 and p.last_recovery['attempted']==0

def test_audible_unsubtitled_gap_is_recovered(monkeypatch):
    p=FasterWhisperProvider(); info=SimpleNamespace(duration_after_vad=1,language='zh',language_probability=1); calls=[]
    first=SimpleNamespace(text=' 前段',start=0,end=1,words=[SimpleNamespace(word='前段',start=0,end=1,probability=.9)])
    retry=SimpleNamespace(text=' 漏段',start=0,end=1,words=[])
    def transcribe(audio, **kwargs):
        calls.append(len(audio))
        return (iter([first]),info) if len(calls)==1 else (iter([retry]),info)
    p.model=SimpleNamespace(transcribe=transcribe); p.device='cpu'
    monkeypatch.setattr(p,'load',lambda *args:None)
    audio=np.concatenate((np.ones(16000,dtype=np.float32)*.1,np.zeros(16000,dtype=np.float32),np.ones(16000,dtype=np.float32)*.1))
    monkeypatch.setattr(module,'chunks',lambda path:iter([(0,audio)]))
    segments,*_=p.transcribe(None,'zh',lambda **v:None)
    assert calls==[48000,24000] and [segment['text'] for segment in segments]==[' 前段',' 漏段']
