"""Persistent last-known-good stream index. Refreshed only when Media Info opens."""
import json, sqlite3, threading, time
from pathlib import Path
_LOCK=threading.Lock()

def _path(profile):
    p=Path(profile)/'cache';p.mkdir(parents=True,exist_ok=True);return str(p/'streams.sqlite')
def _connect(profile):
    db=sqlite3.connect(_path(profile),timeout=2)
    try:db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=NORMAL');db.execute('PRAGMA temp_store=MEMORY')
    except sqlite3.Error:pass
    db.execute('CREATE TABLE IF NOT EXISTS streams (media_type TEXT, identity TEXT, updated REAL, payload TEXT, skipped INTEGER, failed INTEGER, PRIMARY KEY(media_type,identity))')
    return db
def get(profile,kind,identity):
    try:
        with _LOCK:
            db=_connect(profile);row=db.execute('SELECT payload,skipped,failed,updated FROM streams WHERE media_type=? AND identity=?',(kind,identity)).fetchone();db.close()
        if not row:return None
        return json.loads(row[0]),int(row[1] or 0),int(row[2] or 0),float(row[3] or 0)
    except Exception:return None
def put(profile,kind,identity,result):
    if not result or not result[0]:return False
    rows,skipped,failed=result
    safe=[]
    for row in rows:
        if isinstance(row,dict):safe.append({k:row.get(k) for k in ('url','label','provider','detail','subtitles','filename','card') if k in row})
    with _LOCK:
        db=_connect(profile);db.execute('INSERT OR REPLACE INTO streams VALUES (?,?,?,?,?,?)',(kind,identity,time.time(),json.dumps(safe,separators=(',',':'),ensure_ascii=False),int(skipped or 0),int(failed or 0)));db.commit();db.close()
    return True
