"""Persistent response cache with per-category expiry and an optional size cap.

Cache keys are hashes, never provider URLs. NULL expiry means unlimited lifetime;
max_bytes=None means no payload-size cap; zero disables reads/writes.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

_STORED = object()


class DiskCache:
    def __init__(self, directory, max_bytes=64 * 1024 * 1024,
                 category='legacy', ttl=_STORED, legacy_ttl=None):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.path = str(Path(directory) / 'browse.sqlite')
        self.max_bytes = max_bytes
        self.category = category
        self.ttl = ttl
        self.legacy_ttl = legacy_ttl
        with self.connect() as db:
            # Serialize migrations when several Home workers open an old DB.
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS responses '
                       '(key TEXT PRIMARY KEY, expires REAL, used REAL, value TEXT)')
            columns = {row[1] for row in db.execute('PRAGMA table_info(responses)')}
            if 'created' not in columns:
                db.execute('ALTER TABLE responses ADD COLUMN created REAL')
            if 'category' not in columns:
                db.execute("ALTER TABLE responses ADD COLUMN category TEXT NOT NULL DEFAULT 'legacy'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            try:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('PRAGMA synchronous=NORMAL')
                db.execute('PRAGMA temp_store=MEMORY')
            except sqlite3.Error:
                pass
            with db:
                yield db
        finally:
            db.close()

    def _trim(self, db, now):
        db.execute('DELETE FROM responses WHERE expires IS NOT NULL AND expires<=?', (now,))
        if self.max_bytes is None:
            return
        total = db.execute('SELECT COALESCE(SUM(LENGTH(CAST(value AS BLOB))),0) FROM responses').fetchone()[0]
        if total <= self.max_bytes:
            return
        for key, length in db.execute('SELECT key,LENGTH(CAST(value AS BLOB)) FROM responses ORDER BY used,key').fetchall():
            if total <= self.max_bytes:
                break
            db.execute('DELETE FROM responses WHERE key=?', (key,))
            total -= length

    def get(self, url):
        if self.max_bytes == 0 or self.ttl == 0:
            return None
        now = time.time()
        key = hashlib.sha256(url.encode()).hexdigest()
        with self.connect() as db:
            self._trim(db, now)
            row = db.execute('SELECT expires,value,created,category FROM responses WHERE key=?', (key,)).fetchone()
            if not row:
                return None
            expires, raw, created, category = row
            if self.ttl is not _STORED:
                if created is None:
                    # Legacy expiry is based on the previous known default TTL.
                    # Expired legacy entries were already removed above.
                    created = expires - self.legacy_ttl if expires is not None and self.legacy_ttl else now
                expires = None if self.ttl is None else created + self.ttl
                if expires is not None and expires <= now:
                    db.execute('DELETE FROM responses WHERE key=?', (key,))
                    return None
                category = self.category if self.category != 'legacy' else category
                db.execute('UPDATE responses SET expires=?,created=?,category=? WHERE key=?',
                           (expires, created, category, key))
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                db.execute('DELETE FROM responses WHERE key=?', (key,))
                return None
            db.execute('UPDATE responses SET used=? WHERE key=?', (now, key))
        return value

    def put(self, url, value, ttl):
        if self.max_bytes == 0:
            return
        key = hashlib.sha256(url.encode()).hexdigest()
        if ttl is not None and ttl <= 0:
            with self.connect() as db:
                db.execute('DELETE FROM responses WHERE key=?', (key,))
            return
        raw = json.dumps(value, separators=(',', ':'), ensure_ascii=False)
        if self.max_bytes is not None and len(raw.encode('utf-8')) > self.max_bytes:
            return
        now = time.time()
        expires = None if ttl is None else now + ttl
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO responses (key,expires,used,value,created,category) VALUES (?,?,?,?,?,?)',
                       (key, expires, now, raw, now, self.category))
            self._trim(db, now)

    def apply_policy(self, lifetimes):
        """Apply new lifetimes to known categories without touching account data."""
        now = time.time()
        with self.connect() as db:
            # Do not resurrect entries which were already expired.
            db.execute('DELETE FROM responses WHERE expires IS NOT NULL AND expires<=?', (now,))
            for category, ttl in lifetimes.items():
                if ttl == 0:
                    db.execute('DELETE FROM responses WHERE category=?', (category,))
                elif ttl is None:
                    db.execute('UPDATE responses SET expires=NULL WHERE category=? AND created IS NOT NULL', (category,))
                else:
                    db.execute('UPDATE responses SET expires=created+? WHERE category=? AND created IS NOT NULL', (ttl, category))
            self._trim(db, now)

    def clear(self, category=None):
        with self.connect() as db:
            if category is None:
                db.execute('DELETE FROM responses')
            else:
                db.execute('DELETE FROM responses WHERE category=?', (category,))
        # Return free pages to disk when possible; a busy reader may defer VACUUM.
        try:
            db = sqlite3.connect(self.path, timeout=1)
            try:
                db.execute('VACUUM')
            finally:
                db.close()
        except sqlite3.Error:
            pass

    def stats(self):
        with self.connect() as db:
            rows = db.execute('SELECT category,COUNT(*),COALESCE(SUM(LENGTH(CAST(value AS BLOB))),0) '
                              'FROM responses GROUP BY category').fetchall()
        return {'count': sum(row[1] for row in rows), 'bytes': sum(row[2] for row in rows),
                'categories': {row[0]: {'count': row[1], 'bytes': row[2]} for row in rows},
                'database_bytes': Path(self.path).stat().st_size}
