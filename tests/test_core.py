import io
import json
import re
import wave
import pytest
from app.subtitle import stamp, subtitles, export
from app.audio import extract, MediaError, chunks

def sample():
    return [{'id':0,'start':0.2,'end':2.8,'text':'测试 English。','words':[{'word':'测试','start':.2,'end':1.,'probability':.9},{'word':' English。','start':1.1,'end':2.8,'probability':.8}]}]

def test_exports(tmp_path):
    from opencc import OpenCC
    segs=sample(); cues=subtitles(segs,OpenCC('s2twp').convert)
    data={'segments':segs,'subtitles':cues}
    export(data,tmp_path)
    assert len(list(tmp_path.iterdir()))==5
    assert '測試 English。' in (tmp_path/'transcript.txt').read_text('utf-8')
    assert (tmp_path/'transcript.vtt').read_text('utf-8').startswith('WEBVTT\n\n')
    assert re.search(r'00:00:00,200 --> 00:00:02,800',(tmp_path/'transcript.srt').read_text('utf-8'))
    assert '[00:00:00.200 - 00:00:02.800]' in (tmp_path/'transcript.timed.txt').read_text('utf-8')
    assert json.loads((tmp_path/'transcript.json').read_text('utf-8'))['segments']==segs
    assert all(c['start']<c['end'] for c in cues)
    assert stamp(3599.9996)=='01:00:00,000'

def test_boundaries_and_text():
    words=[{'word':'字','start':i*.2,'end':i*.2+.18,'probability':1} for i in range(100)]
    cues=subtitles([{'start':0,'end':20,'text':'字'*100,'words':words}])
    assert ''.join(c['text'] for c in cues)=='字'*100
    assert all(a['end']<=b['start'] for a,b in zip(cues,cues[1:]))

def test_audio(tmp_path):
    source=tmp_path/'test.wav'
    with wave.open(str(source),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*32000)
    target=tmp_path/'out.wav'
    assert extract(source,target)==2
    assert [(offset,len(data)) for offset,data in chunks(target,1)]==[(0,16000),(1,16000)]
    source.write_text('not a media file')
    with pytest.raises(MediaError):extract(source,target)

@pytest.mark.parametrize('duration', [610, 7500])
def test_long_audio_chunk_offsets(tmp_path,duration):
    source=tmp_path/'long.wav'
    with wave.open(str(source),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000)
        for _ in range(duration):w.writeframes(b'\0\0'*16000)
    blocks=[(offset,len(audio)) for offset,audio in chunks(source)]
    assert len(blocks)>=3
    assert sum(n for _,n in blocks)==duration*16000
    assert all(n<=300*16000 for _,n in blocks)
    assert all(abs(offset+n/16000-next_offset)<1e-8 for (offset,n),(next_offset,_) in zip(blocks,blocks[1:]))

def test_zero_length_word_does_not_drop_text():
    data=sample()
    data[0]['words'][0]['end']=data[0]['words'][0]['start']
    assert ''.join(c['text'] for c in subtitles(data))==data[0]['text']
