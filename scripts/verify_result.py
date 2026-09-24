"""Verify a real completed job over HTTP; no mock transcription."""
import json
import re
import urllib.request

BASE='http://127.0.0.1:8000'
def get(path):
    with urllib.request.urlopen(BASE+path) as response:
        return response.read()

jobs=json.loads(get('/api/jobs'))
completed=[j for j in jobs if j['status']=='done']
if not completed:
    print(json.dumps(jobs,ensure_ascii=False,indent=2))
    raise SystemExit('No completed job yet')
job=completed[0]; prefix='/api/jobs/'+job['id']
result=json.loads(get(prefix+'/result'))
assert result['device']=='cuda', result['device']
assert result['compute_type']=='float16'
assert result['model']=='large-v3'
assert result['segments'] and any(s['words'] for s in result['segments'])
assert all(s['start']<s['end'] for s in result['segments'])
assert all(a['end']<=b['start']+.1 for a,b in zip(result['segments'],result['segments'][1:]))
for format in ('srt','vtt','txt','timed.txt','json'):
    content=get(prefix+'/download/'+format).decode('utf-8').replace('\r\n','\n')
    assert content.strip()
    if format=='srt':assert re.search(r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}',content)
    if format=='vtt':assert content.startswith('WEBVTT\n\n')
assert get(prefix+'/preview')
print(json.dumps({k:result[k] for k in ('file','duration','model','device','compute_type','processing_seconds','real_time_factor')},ensure_ascii=False,indent=2))
print('Segments:',len(result['segments']),'Words:',sum(len(s['words']) for s in result['segments']))
print('All five HTTP downloads and preview audio verified.')
