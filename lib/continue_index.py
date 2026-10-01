"""SQLite-backed Continue Watching index for fast Kodi Home rendering."""
import json, sqlite3, threading, time
from pathlib import Path

_lock=threading.RLock()
LOGIC_VERSION=2

def _path(profile): return Path(profile)/'continue_index.sqlite'
def _db(profile):
    db=sqlite3.connect(str(_path(profile)),timeout=2)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE IF NOT EXISTS continue_items (
      media_type TEXT NOT NULL, media_id TEXT NOT NULL, status TEXT NOT NULL,
      last_video_id TEXT, next_video_id TEXT, next_release TEXT,
      progress_ms INTEGER NOT NULL DEFAULT 0, last_watched TEXT,
      item_json TEXT NOT NULL, source_mtime TEXT, updated REAL NOT NULL, next_check REAL NOT NULL DEFAULT 0,
      PRIMARY KEY(media_type,media_id))''')
    
    try: db.execute('ALTER TABLE continue_items ADD COLUMN next_check REAL NOT NULL DEFAULT 0')
    except sqlite3.OperationalError: pass
    db.execute('CREATE INDEX IF NOT EXISTS cw_status_recent ON continue_items(status,last_watched DESC)')
    db.execute('CREATE TABLE IF NOT EXISTS continue_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    row=db.execute("SELECT value FROM continue_meta WHERE key='logic_version'").fetchone()
    if not row or str(row[0])!=str(LOGIC_VERSION):
        db.execute('DELETE FROM continue_items')
        db.execute("INSERT OR REPLACE INTO continue_meta(key,value) VALUES('logic_version',?)",(str(LOGIC_VERSION),))
        db.commit()
    return db

def seed(profile, library):
    """Import all plausible CW pointers from Stremio without network metadata."""
    now=time.time(); seen=set()
    with _lock:
      db=_db(profile)
      try:
        for row in library or []:
          if not isinstance(row,dict) or row.get('type') not in ('movie','series'): continue
          state=row.get('state') if isinstance(row.get('state'),dict) else {}
          media_id=str(row.get('_id') or row.get('id') or ''); typ=row.get('type')
          if not media_id: continue
          try: offset=max(0,int(float(state.get('timeOffset') or 0)))
          except (TypeError,ValueError): offset=0
          try: duration=max(0,int(float(state.get('duration') or 0)))
          except (TypeError,ValueError): duration=0
          completed = bool(state.get('flaggedWatched')) or (duration>0 and offset>=duration*0.90)
          # Movies belong in CW only for genuine incomplete progress. A stale
          # offset on a watched/90%+ movie must never resurrect it.
          movie_pointer=typ=='movie' and offset>0 and not completed
          # Series keep completed episode pointers only as unresolved candidates;
          # metadata must prove an already-aired next episode before Home shows them.
          series_pointer=typ=='series' and bool(state.get('video_id')) and (offset>0 or completed)
          if not (series_pointer or movie_pointer): continue
          status=('waiting' if typ=='series' and completed else 'partial')
          key=(typ,media_id);seen.add(key)
          item=dict(row,id=media_id);mtime=str(row.get('_mtime') or '');video_id=str(state.get('video_id') or '')
          existing=db.execute('SELECT status,last_video_id,source_mtime,next_video_id,next_release,item_json FROM continue_items WHERE media_type=? AND media_id=?',key).fetchone()
          if existing and existing[1]==video_id and existing[2]==mtime and existing[0] in ('next_ready','finished'):
            # No Stremio state change: preserve the resolved episode/status.
            db.execute('UPDATE continue_items SET last_watched=?,updated=? WHERE media_type=? AND media_id=?',(str(state.get('lastWatched') or mtime),now,typ,media_id))
          else:
            db.execute('''INSERT INTO continue_items(media_type,media_id,status,last_video_id,next_video_id,next_release,progress_ms,last_watched,item_json,source_mtime,updated)
              VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(media_type,media_id) DO UPDATE SET
              status=excluded.status,last_video_id=excluded.last_video_id,next_video_id=NULL,next_release=NULL,progress_ms=excluded.progress_ms,
              last_watched=excluded.last_watched,item_json=excluded.item_json,source_mtime=excluded.source_mtime,updated=excluded.updated''',
              (typ,media_id,status,video_id,None,None,offset,str(state.get('lastWatched') or mtime),json.dumps(item,separators=(',',':')),mtime,now))
        # Entries no longer represented by Stremio CW state are removed. Resolved waiting/finished
        # rows remain represented because completed series pointers are seeded above.
        rows=db.execute('SELECT media_type,media_id FROM continue_items').fetchall()
        for key in rows:
          if tuple(key) not in seen: db.execute('DELETE FROM continue_items WHERE media_type=? AND media_id=?',key)
        db.commit()
      finally: db.close()

def resolve_series(profile, media_id, item, target, resume_ms=0):
    status='next_ready' if target else 'finished'
    next_id=str((target or {}).get('id') or '')
    release=str((target or {}).get('released') or (target or {}).get('firstAired') or '')
    display=dict(item)
    display['state']=dict(display.get('state') or {})
    if target:
      display['state']['video_id']=next_id;display['state']['timeOffset']=int(resume_ms) if resume_ms else 1
    with _lock:
      db=_db(profile)
      try:
       db.execute('UPDATE continue_items SET status=?,next_video_id=?,next_release=?,progress_ms=?,item_json=?,updated=?,next_check=? WHERE media_type=? AND media_id=?',
                  (status,next_id,release,int(resume_ms or 0),json.dumps(display,separators=(',',':')),time.time(),time.time()+(86400 if status=='finished' else 0),'series',media_id));db.commit()
      finally: db.close()

def rows(profile, limit=100):
    with _lock:
      db=_db(profile)
      try: data=db.execute("SELECT item_json FROM continue_items WHERE status IN ('partial','next_ready') ORDER BY last_watched DESC LIMIT ?",(int(limit),)).fetchall()
      finally: db.close()
    out=[]
    for (raw,) in data:
      try: out.append(json.loads(raw))
      except Exception: pass
    return out

def unresolved_series(profile, limit=32):
    with _lock:
      db=_db(profile)
      try:data=db.execute("SELECT media_id,item_json FROM continue_items WHERE media_type='series' AND (status='waiting' OR (status='finished' AND next_check<=?)) ORDER BY CASE WHEN status='waiting' THEN 0 ELSE 1 END,last_watched DESC LIMIT ?",(time.time(),int(limit))).fetchall()
      finally:db.close()
    out=[]
    for media_id,raw in data:
      try:out.append((media_id,json.loads(raw)))
      except Exception:pass
    return out
