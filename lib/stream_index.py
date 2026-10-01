"""Persistent stream cache: instant last-known-good rows with bounded background refresh."""
import hashlib,json,sqlite3,threading,time
from pathlib import Path
_LOCK=threading.Lock(); TTL=15*60; MAX_AGE=24*60*60

def _path(profile):
    p=Path(profile)/'cache';p.mkdir(parents=True,exist_ok=True);return str(p/'streams.sqlite')
def _connect(profile):
    db=sqlite3.connect(_path(profile),timeout=2)
    try:db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=NORMAL');db.execute('PRAGMA temp_store=MEMORY')
    except sqlite3.Error:pass
    db.execute('''CREATE TABLE IF NOT EXISTS streams (media_type TEXT, identity TEXT, updated REAL, payload TEXT,
      skipped INTEGER, failed INTEGER, provider_sig TEXT NOT NULL DEFAULT '', last_verified REAL NOT NULL DEFAULT 0,
      PRIMARY KEY(media_type,identity))''')
    cols={r[1] for r in db.execute('PRAGMA table_info(streams)')}
    for name,decl in [('provider_sig',"TEXT NOT NULL DEFAULT ''"),('last_verified','REAL NOT NULL DEFAULT 0')]:
      if name not in cols:
       try:db.execute('ALTER TABLE streams ADD COLUMN '+name+' '+decl)
       except sqlite3.Error:pass
    return db

def provider_signature(providers):
    values=[]
    for p in providers or []:
      if not isinstance(p,dict):continue
      m=p.get('manifest') if isinstance(p.get('manifest'),dict) else {}
      values.append(str(m.get('id') or '')+'|'+str(m.get('version') or '')+'|'+str(p.get('transportUrl') or ''))
    return hashlib.sha256('\n'.join(values).encode()).hexdigest() if values else ''

def get(profile,kind,identity,provider_sig=''):
    try:
      with _LOCK:
        db=_connect(profile);row=db.execute('SELECT payload,skipped,failed,updated,provider_sig,last_verified FROM streams WHERE media_type=? AND identity=?',(kind,identity)).fetchone();db.close()
      if not row:return None
      rows=json.loads(row[0]);updated=float(row[3] or 0);stored_sig=str(row[4] or '');now=time.time()
      if provider_sig and stored_sig and stored_sig!=provider_sig:return None
      age=max(0,now-updated)
      if age>MAX_AGE:return None
      return rows,int(row[1] or 0),int(row[2] or 0),updated,age>TTL,float(row[5] or 0)
    except Exception:return None

def put(profile,kind,identity,result,provider_sig=''):
    if not result or not result[0]:return False
    rows,skipped,failed=result;safe=[]
    for row in rows:
      if isinstance(row,dict):safe.append({k:row.get(k) for k in ('url','label','provider','detail','subtitles','filename','card') if k in row})
    now=time.time()
    with _LOCK:
      db=_connect(profile);db.execute('''INSERT OR REPLACE INTO streams
        (media_type,identity,updated,payload,skipped,failed,provider_sig,last_verified) VALUES (?,?,?,?,?,?,?,?)''',
        (kind,identity,now,json.dumps(safe,separators=(',',':'),ensure_ascii=False),int(skipped or 0),int(failed or 0),str(provider_sig or ''),now));db.commit();db.close()
    return True

def prune(profile):
    try:
      with _LOCK:
       db=_connect(profile);db.execute('DELETE FROM streams WHERE updated<?',(time.time()-MAX_AGE,));n=db.total_changes;db.commit();db.close();return n
    except Exception:return 0
