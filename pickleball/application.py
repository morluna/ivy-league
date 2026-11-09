import copy
import secrets
import threading
import unicodedata
import time
from collections import OrderedDict
from .domain import schedule, validate, players_per_court
from .security import digest, matches
from .ports import RepositoryConflict, StorageUnavailable

class AppError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

class Sessions:
    def __init__(self, repository, clock, realtime, admin_key=None, read_cache_seconds=0, monotonic=time.monotonic):
        self.repo, self.clock, self.realtime = repository, clock, realtime
        self.lock = threading.RLock()
        self.read_cache_seconds, self.monotonic = read_cache_seconds, monotonic
        self.read_cache = OrderedDict()
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

    def _court_names(self, values, count):
        if values is None:
            return ['Court %s' % (i + 1) for i in range(count)]
        if not isinstance(values, list) or len(values) != count:
            raise AppError('Provide one name for each court.')
        names = []
        for i, value in enumerate(values):
            if not isinstance(value, str):
                raise AppError('Court names must be text.')
            names.append(self._name(value) if value.strip() else 'Court %s' % (i + 1))
        if len({name.casefold() for name in names}) != len(names):
            raise AppError('Court names must be distinct.')
        return names

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
            self.read_cache.pop(s['id'], None)
            raise AppError('The session changed on another device. Refresh and try again.', 409) from None
        except StorageUnavailable:
            self.read_cache.pop(s['id'], None)
            raise
        self._remember(s)
        self.realtime.publish(s['id'], s['revision'])

    def _view(self, s):
        result = copy.deepcopy(s)
        result.pop('organizer_token')
        for p in result['players']:
            p.pop('token')
        result['play_format'] = s.get('play_format', 'doubles')
        result['court_names'] = self._court_names(s.get('court_names'), s['courts'])
        result['status'] = 'closed' if s['timer']['state'] == 'finished' else 'open'
        result['server_now'] = self.clock.now()
        return result

    def _remember(self, s):
        if self.read_cache_seconds > 0:
            self.read_cache[s['id']] = (self.monotonic() + self.read_cache_seconds, copy.deepcopy(s))
            self.read_cache.move_to_end(s['id'])
            while len(self.read_cache) > 128:
                self.read_cache.popitem(last=False)

    def get(self, sid):
        with self.lock:
            cached = self.read_cache.get(sid)
            if cached and cached[0] > self.monotonic():
                self.read_cache.move_to_end(sid)
                return self._view(cached[1])
            self.read_cache.pop(sid, None)
            s = self._load(sid)
            self._remember(s)
            return self._view(s)


    def create(self, name, courts=2, duration=120, length=None, court_names=None, play_format='doubles'):
        validate(courts, duration, length, play_format)
        name = self._name(name)
        court_names = self._court_names(court_names, courts)
        with self.lock:
            token, pid = secrets.token_urlsafe(24), secrets.token_urlsafe(12)
            s = dict(id=secrets.token_urlsafe(12), organizer_token=digest(token), seed=secrets.token_hex(8),
                     courts=courts, court_names=court_names, play_format=play_format, duration=duration, length=length, revision=0,
                     players=[dict(id=pid, name=name, active=True, token=digest(token))], rounds=[], current=-1,
                     timer=dict(state='idle', started_at=None, remaining=length * 60 if length is not None else None))
            self._reschedule(s)
            self._save(s)
            return dict(session=self._view(s), token=token, player_id=pid)

    def _reschedule(self, s):
        # current is the last started round: freeze it and every earlier round,
        # even when paused, expired, or between rounds. Only unstarted rounds change.
        frozen = s['rounds'][:s['current'] + 1]
        ids = [p['id'] for p in s['players'] if p['active']]
        count = s['duration'] // s['length'] if s['length'] is not None else min(96, max(12, len(s['rounds']), len(frozen) + 1))
        s['rounds'] = frozen + schedule(ids, s['courts'], count - len(frozen), s['seed'], frozen, play_format=s.get('play_format', 'doubles'))

    def _begin_round(self, s, now):
        index = s['current'] + 1
        if index >= len(s['rounds']) and s['length'] is None:
            if index >= 96:
                raise AppError('This session has reached 96 rounds. End it and create a new session.')
            ids = [p['id'] for p in s['players'] if p['active']]
            s['rounds'] += schedule(ids, s['courts'], 1, s['seed'], s['rounds'], play_format=s.get('play_format', 'doubles'))
        if index >= len(s['rounds']) or not s['rounds'][index]['matches']:
            raise AppError('At least %s active players and an available round are required.' % players_per_court(s.get('play_format', 'doubles')))
        s['current'] = index
        s['timer'].update(state='running', started_at=now,
                          remaining=s['length'] * 60 if s['length'] is not None else None, elapsed=0)

    def _capture_elapsed(self, s, now):
        if s['length'] is None and s['timer']['state'] == 'running':
            s['timer']['elapsed'] = max(0, now - s['timer']['started_at'])

    def _close(self, s, by):
        if s['timer']['state'] != 'finished':
            self._capture_elapsed(s, self.clock.now())
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
            if action in ('join', 'add-player'):
                if action == 'add-player' and not organizer:
                    raise AppError('Only the organizer can add players.', 403)
                if action == 'join' and actor:
                    # Idempotent retries return the same identity, including after departure.
                    return dict(session=self._view(s), token=token, player_id=actor['id'])
                name = self._name(data.get('name'))
                existing = next((p for p in s['players'] if p['name'].casefold() == name.casefold()), None)
                if existing:
                    if action == 'add-player' and not existing['active']:
                        existing['active'] = True
                        self._reschedule(s)
                        self._save(s)
                        return dict(session=self._view(s))
                    raise AppError('That name is already used. Choose a distinct name.', 409)
                if len(s['players']) >= 64:
                    raise AppError('This session has reached its 64-player limit.')
                token, pid = secrets.token_urlsafe(24), secrets.token_urlsafe(12)
                s['players'].append(dict(id=pid, name=name, active=True, token=digest(token)))
                self._reschedule(s)
                self._save(s)
                if action == 'add-player':
                    # The organizer keeps their own identity; this is a roster place.
                    return dict(session=self._view(s))
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
                if action == 'court-names':
                    if not isinstance(data.get('names'), list):
                        raise AppError('Provide one name for each court.')
                    s['court_names'] = self._court_names(data['names'], s['courts'])
                elif action == 'settings':
                    if s['current'] >= 0:
                        raise AppError('Settings are locked after the first round starts.')
                    play_format = data.get('play_format', s.get('play_format', 'doubles'))
                    validate(data.get('courts'), data.get('duration'), data.get('length'), play_format)
                    old_names = self._court_names(s.get('court_names'), s['courts'])
                    resized = old_names[:data['courts']] + ['Court %s' % (i + 1) for i in range(len(old_names), data['courts'])]
                    s['court_names'] = self._court_names(resized, data['courts'])
                    for k in ('courts', 'duration', 'length'):
                        s[k] = data[k]
                    s['play_format'] = play_format
                    timer['remaining'] = s['length'] * 60 if s['length'] is not None else None
                    self._reschedule(s)
                elif action == 'start':
                    if timer['state'] not in ('idle', 'ended'):
                        raise AppError('End the current round before starting another.')
                    self._begin_round(s, now)
                elif action == 'next':
                    if s['length'] is not None or timer['state'] != 'running':
                        raise AppError('Next round is available during an active manual round.')
                    # Validate and start the next round atomically; a failed advance
                    # leaves the current round and its count-up clock untouched.
                    self._begin_round(s, now)
                elif action == 'pause':
                    if s['length'] is None:
                        raise AppError('Manual rounds advance with Next round.')
                    if timer['state'] != 'running':
                        raise AppError('The timer is not running.')
                    timer.update(state='paused', remaining=max(0, timer['remaining'] - (now - timer['started_at'])), started_at=None)
                elif action == 'resume':
                    if s['length'] is None:
                        raise AppError('Manual rounds advance with Next round.')
                    if timer['state'] != 'paused' or timer['remaining'] <= 0:
                        raise AppError('There is no paused time left to resume.')
                    timer.update(state='running', started_at=now)
                elif action == 'end':
                    if timer['state'] not in ('running', 'paused'):
                        raise AppError('There is no active round.')
                    self._capture_elapsed(s, now)
                    timer.update(state='finished' if s['length'] is not None and s['current'] + 1 == len(s['rounds']) else 'ended', remaining=0, started_at=None)
                    if timer['state'] == 'finished':
                        s.update(closed_at=now, closed_by='completed')
                else:
                    raise AppError('Unknown action.')
            self._save(s)
            return dict(session=self._view(s))
