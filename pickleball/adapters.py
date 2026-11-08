import copy
import json
import sqlite3
import time
from .security import protect

class SystemClock:
    def now(self):
        return time.time()

class MemoryRepository:
    def __init__(self):
        self.data = {}
    def get(self, key):
        return copy.deepcopy(self.data.get(key))
    def save(self, session):
        self.data[session['id']] = copy.deepcopy(session)

class SQLiteRepository:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            for sid, body in db.execute('SELECT id, body FROM sessions').fetchall():
                migrated = json.dumps(protect(json.loads(body)))
                if migrated != body:
                    db.execute('UPDATE sessions SET body = ? WHERE id = ?', (migrated, sid))
    def get(self, key):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT body FROM sessions WHERE id = ?', (key,)).fetchone()
        return json.loads(row[0]) if row else None
    def save(self, session):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (session['id'], json.dumps(session)))

class SnapshotRealtime:
    """Local transport polls durable revisioned snapshots; reconnect needs no event replay."""
    def publish(self, session_id, revision):
        pass
