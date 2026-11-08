"""Capability digests and bounded, process-local rate limits for the single-instance pilot."""
import hashlib
import secrets
import threading
import time


def digest(token):
    return 'sha256:' + hashlib.sha256(token.encode('utf-8')).hexdigest()


def matches(token, stored):
    if not isinstance(token, str) or not isinstance(stored, str):
        return False
    candidate = digest(token) if stored.startswith('sha256:') else token
    return secrets.compare_digest(candidate.encode(), stored.encode())


def protect(session):
    """Migrate old local capabilities without invalidating existing browser identities."""
    for record, field in [(session, 'organizer_token')] + [(p, 'token') for p in session['players']]:
        if not record[field].startswith('sha256:'):
            record[field] = digest(record[field])
    return session


class RateLimiter:
    def __init__(self, now=time.monotonic):
        self.now, self.entries, self.lock = now, {}, threading.Lock()

    def allow(self, key, limit, seconds=60):
        now = self.now()
        with self.lock:
            self.entries = {k:v for k,v in self.entries.items() if v[1] > now}
            count, expiry = self.entries.get(key, (0, now + seconds))
            if count >= limit or (key not in self.entries and len(self.entries) >= 10000):
                return False
            self.entries[key] = (count + 1, expiry)
            return True
