import copy
import secrets
import threading
import unicodedata
from .domain import schedule, validate
from .security import digest, matches
from .ports import RepositoryConflict

class AppError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

class Sessions:
    def __init__(self, repository, clock, realtime, admin_key=None):
        self.repo, self.clock, self.realtime = repository, clock, realtime
        self.lock = threading.RLock()
        if admin_key is not None and len(admin_key) < 32:
            raise ValueError('SESSION_ADMIN_KEY must contain at least 32 characters.')
        self.admin_hash = digest(admin_key) if admin_key else None

    def _name(self, value):
        if not isinstance(value, str):
            raise AppError('Enter a name.')
        value = unicodedata.normalize('NFKC', value).strip()
        if not value or len(value) > 40 or any(unicodedata.category(c).startswith('C') for c in value):
            raise AppError('Names must contain 1–40 visible characters.')
        return value

    def _load(self, sid):
        s = self.repo.get(sid)
        if not s:
            raise AppError('Session not found.', 404)
        return s

    def _save(self, s):
        previous = s['revision']
        s['revision'] += 1
        try:
            self.repo.save(s, expected_revision=previous)
        except RepositoryConflict:
            raise AppError('The session changed on another device. Refresh and try again.', 409) from None
        self.realtime.publish(s['id'], s['revision'])

    def _view(self, s):
        result = copy.deepcopy(s)
        result.pop('organizer_token')
        for p in result['players']:
            p.pop('token')
        result['status'] = 'closed' if s['timer']['state'] == 'finished' else 'open'
        result['server_now'] = self.clock.now()
        return result

    def get(self, sid):
        with self.lock:
            return self._view(self._load(sid))

    def create(self, name, courts=2, duration=120, length=10):
        validate(courts, duration, length)
        name = self._name(name)
        with self.lock:
            token, pid = secrets.token_urlsafe(24), secrets.token_urlsafe(12)
            s = dict(id=secrets.token_urlsafe(12), organizer_token=digest(token), seed=secrets.token_hex(8),
                     courts=courts, duration=duration, length=length, revision=0,
                     players=[dict(id=pid, name=name, active=True, token=digest(token))], rounds=[], current=-1,
                     timer=dict(state='idle', started_at=None, remaining=length * 60))
            self._reschedule(s)
            self._save(s)
            return dict(session=self._view(s), token=token, player_id=pid)

    def _reschedule(self, s):
        frozen = s['rounds'][:s['current'] + 1]
        ids = [p['id'] for p in s['players'] if p['active']]
        count = s['duration'] // s['length']
        s['rounds'] = frozen + schedule(ids, s['courts'], count - len(frozen), s['seed'], frozen)

    def _close(self, s, by):
        if s['timer']['state'] != 'finished':
            s['timer'].update(state='finished', started_at=None, remaining=0)
            s.update(closed_at=self.clock.now(), closed_by=by)
            self._save(s)
        return dict(session=self._view(s))

    def force_end(self, sid, token):
        # Owner authority is separate from every organizer/participant capability.
        if not self.admin_hash or not matches(token, self.admin_hash):
            raise AppError('Owner access required.', 403)
        with self.lock:
            return self._close(self._load(sid), 'owner')

    def mutate(self, sid, action, token=None, **data):
        with self.lock:
            s = self._load(sid)
            organizer = bool(token) and matches(token, s['organizer_token'])
            actor = next((p for p in s['players'] if token and matches(token, p['token'])), None)
            if action == 'end-session':
                if not organizer:
                    raise AppError('Only the organizer can end the session.', 403)
                return self._close(s, 'organizer')
            if s['timer']['state'] == 'finished':
                raise AppError('This session has ended and is read-only.', 409)
            if action == 'join':
                if actor:
                    # Idempotent retries return the same identity, including after departure.
                    return dict(session=self._view(s), token=token, player_id=actor['id'])
                name = self._name(data.get('name'))
                if any(p['name'].casefold() == name.casefold() for p in s['players']):
                    raise AppError('That name is already used. Choose a distinct name.', 409)
                if len(s['players']) >= 64:
                    raise AppError('This session has reached its 64-player limit.')
                token, pid = secrets.token_urlsafe(24), secrets.token_urlsafe(12)
                s['players'].append(dict(id=pid, name=name, active=True, token=digest(token)))
                self._reschedule(s)
                self._save(s)
                return dict(session=self._view(s), token=token, player_id=pid)
            if action == 'leave':
                target = data.get('player_id') or (actor['id'] if actor else None)
                if not organizer and (not actor or actor['id'] != target):
                    raise AppError('You can only remove yourself.', 403)
                player = next((p for p in s['players'] if p['id'] == target), None)
                if not player:
                    raise AppError('Player not found.', 404)
                player['active'] = False
                self._reschedule(s)
            else:
                if not organizer:
                    raise AppError('Only the organizer can control the session.', 403)
                timer = s['timer']
                now = self.clock.now()
                if action == 'settings':
                    if s['current'] >= 0:
                        raise AppError('Settings are locked after the first round starts.')
                    validate(data.get('courts'), data.get('duration'), data.get('length'))
                    for k in ('courts', 'duration', 'length'):
                        s[k] = data[k]
                    timer['remaining'] = s['length'] * 60
                    self._reschedule(s)
                elif action == 'start':
                    if timer['state'] not in ('idle', 'ended'):
                        raise AppError('End the current round before starting another.')
                    index = s['current'] + 1
                    if index >= len(s['rounds']) or not s['rounds'][index]['matches']:
                        raise AppError('At least four active players and an available round are required.')
                    s['current'] = index
                    timer.update(state='running', started_at=now, remaining=s['length'] * 60)
                elif action == 'pause':
                    if timer['state'] != 'running':
                        raise AppError('The timer is not running.')
                    timer.update(state='paused', remaining=max(0, timer['remaining'] - (now - timer['started_at'])), started_at=None)
                elif action == 'resume':
                    if timer['state'] != 'paused' or timer['remaining'] <= 0:
                        raise AppError('There is no paused time left to resume.')
                    timer.update(state='running', started_at=now)
                elif action == 'end':
                    if timer['state'] not in ('running', 'paused'):
                        raise AppError('There is no active round.')
                    timer.update(state='finished' if s['current'] + 1 == len(s['rounds']) else 'ended', remaining=0, started_at=None)
                    if timer['state'] == 'finished':
                        s.update(closed_at=now, closed_by='completed')
                else:
                    raise AppError('Unknown action.')
            self._save(s)
            return dict(session=self._view(s))
