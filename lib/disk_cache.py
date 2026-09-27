"""Bounded, persistent JSON cache for catalog and metadata responses."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time


class DiskCache:
    def __init__(self, directory, max_bytes=64 * 1024 * 1024):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.path = str(Path(directory) / 'browse.sqlite')
        self.max_bytes = max_bytes
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, expires REAL, used REAL, value TEXT)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, url):
        now = time.time()
        key = hashlib.sha256(url.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute('SELECT expires,value FROM responses WHERE key=?', (key,)).fetchone()
            if not row or row[0] <= now:
                return None
            db.execute('UPDATE responses SET used=? WHERE key=?', (now, key))
        return json.loads(row[1])

    def put(self, url, value, ttl):
        raw = json.dumps(value, separators=(',', ':'))
        size = len(raw.encode())
        if size > self.max_bytes:
            return
        now = time.time()
        key = hashlib.sha256(url.encode()).hexdigest()
        with self.connect() as db:
            db.execute('DELETE FROM responses WHERE expires<=?', (now,))
            db.execute('INSERT OR REPLACE INTO responses VALUES (?,?,?,?)', (key, now + ttl, now, raw))
            total = db.execute('SELECT COALESCE(SUM(LENGTH(CAST(value AS BLOB))),0) FROM responses').fetchone()[0]
            for old_key, length in db.execute('SELECT key,LENGTH(CAST(value AS BLOB)) FROM responses ORDER BY used').fetchall():
                if total <= self.max_bytes:
                    break
                db.execute('DELETE FROM responses WHERE key=?', (old_key,))
                total -= length
