import copy
import json
import sqlite3
import time
import threading
from .ports import RepositoryConflict
from .security import protect

class SystemClock:
    def now(self):
        return time.time()

class MemoryRepository:
    def __init__(self):
        self.data = {}
        self.lock = threading.RLock()
    def get(self, key):
        with self.lock:
            return copy.deepcopy(self.data.get(key))
    def save(self, session, expected_revision=None):
        expected = session['revision']-1 if expected_revision is None else expected_revision
        with self.lock:
            current = self.data.get(session['id'])
            if (current['revision'] if current else 0) != expected:
                raise RepositoryConflict()
            self.data[session['id']] = copy.deepcopy(session)

class SQLiteRepository:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            for sid, body in db.execute('SELECT id, body FROM sessions').fetchall():
                migrated = json.dumps(protect(json.loads(body)))
                if migrated != body:
                    db.execute('UPDATE sessions SET body = ? WHERE id = ?', (migrated, sid))
    def get(self, key):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT body FROM sessions WHERE id = ?', (key,)).fetchone()
        return json.loads(row[0]) if row else None
    def save(self, session, expected_revision=None):
        expected = session['revision']-1 if expected_revision is None else expected_revision
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM sessions WHERE id = ?', (session['id'],)).fetchone()
            if (json.loads(row[0])['revision'] if row else 0) != expected:
                raise RepositoryConflict()
            db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (session['id'], json.dumps(session)))

class SnapshotRealtime:
    """Local transport polls durable revisioned snapshots; reconnect needs no event replay."""
    def publish(self, session_id, revision):
        pass


def repository_from_environment(default_path):
    """Explicit selection: a misconfigured cloud adapter never silently uses local storage."""
    import os
    from pathlib import Path
    backend = os.environ.get('STORAGE_BACKEND','sqlite')
    if backend == 'supabase':
        from .supabase import SupabaseRepository
        return SupabaseRepository(os.environ.get('SUPABASE_URL',''),os.environ.get('SUPABASE_SECRET_KEY',''))
    if backend != 'sqlite':
        raise ValueError('STORAGE_BACKEND must be sqlite or supabase.')
    path = Path(os.environ.get('DATABASE_PATH',str(default_path)))
    path.parent.mkdir(parents=True,exist_ok=True)
    return SQLiteRepository(str(path))
