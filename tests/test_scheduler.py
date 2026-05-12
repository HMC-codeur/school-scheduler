import threading, time, urllib.request, json
import uvicorn
from backend.main import app


def req(method, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(f'http://127.0.0.1:8123{path}', data=body, method=method, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(r) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


def test_full_flow():
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8123, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start(); time.sleep(0.8)
    req('POST','/reset')
    c = req('POST','/classes', {'name':'A','max_lessons_per_day':6})
    t = req('POST','/teachers', {'name':'T1','subject_ids':[],'unavailable_slot_ids':[],'max_lessons_per_day':6})
    s = req('POST','/slots', {'label':'Mon-08:00'})
    sub = req('POST','/subjects', {'name':'Math','weekly_hours':1,'allowed_teacher_ids':[t['id']],'target_class_ids':[c['id']]})
    gen = req('POST','/schedule/generate')
    assert gen['success'] is True
    assert req('GET','/schedule/validate')['valid'] is True
    assert 'créneau' in urllib.request.urlopen('http://127.0.0.1:8123/schedule/export/csv').read().decode()
    sess = req('GET','/schedule')[0]
    req('PUT',f"/schedule/session/{sess['session_id']}", {'class_id':c['id'],'teacher_id':t['id'],'subject_id':sub['id'],'slot_id':s['id']})
    req('DELETE','/schedule')
    assert req('GET','/schedule') == []
    req('POST','/reset')
    assert req('GET','/classes') == []
    server.should_exit = True
