"""Shared HTTP gateway for local server and production WSGI transport."""
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from .application import AppError
from .security import RateLimiter
from .ports import StorageUnavailable

STATIC = Path(__file__).resolve().parent.parent / 'static'
ASSETS = {'/':('index.html','text/html; charset=utf-8'), '/index.html':('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript; charset=utf-8'), '/style.css':('style.css','text/css; charset=utf-8'), '/admin':('admin.html','text/html; charset=utf-8'), '/admin.js':('admin.js','text/javascript; charset=utf-8')}

class Gateway:
    def __init__(self, app, public_origin=None, limiter=None, monotonic=time.monotonic):
        self.app, self.public_origin = app, public_origin
        self.limiter = limiter or RateLimiter()
        self.monotonic, self.health_cached = monotonic, None
        self.health_lock = threading.Lock()
        if public_origin:
            parsed = urlparse(public_origin)
            if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
                raise ValueError('PUBLIC_ORIGIN must be an HTTPS origin without a trailing slash.')

    def handle(self, method, path, headers, body=b'', ip='local'):
        path = urlparse(path).path
        if method == 'GET' and path == '/healthz':
            # Collapse the host's frequent probes. Still check the actual store,
            # with a 30-second success TTL and 5-second failure TTL.
            with self.health_lock:
                now = self.monotonic()
                if not self.health_cached or self.health_cached[0] <= now:
                    try:
                        self.app.repo.get('__health__')
                        status, payload = 200, {'status':'ok'}
                    except Exception:
                        status, payload = 503, {'error':'Storage unavailable.'}
                    ttl = 30 if status == 200 else 5
                    self.health_cached = (self.monotonic()+ttl, status, payload)
                _, status, payload = self.health_cached
                return self.json(status, payload)
        if not self.limiter.allow((ip,'all'), 1200):
            return self.json(429, {'error':'Too many requests. Try again in a minute.'})
        try:
            if method == 'GET':
                if path.startswith('/api/sessions/') and len(path.split('/')) == 4:
                    session = self.app.get(path.split('/')[-1])
                    etag = '"r%s"' % session['revision']
                    status, response_headers, payload = self.json(200, session)
                    response_headers.update(ETag=etag, **{'X-Server-Time':str(session['server_now'])})
                    if headers.get('if-none-match') == etag:
                        return 304, response_headers, b''
                    return status, response_headers, payload
                if path in ASSETS:
                    filename, mime = ASSETS[path]
                    return 200, {'Content-Type':mime,'Cache-Control':'no-cache'}, (STATIC / filename).read_bytes()
                raise AppError('Not found.',404)
            if method != 'POST':
                raise AppError('Method not allowed.',405)
            expected_origin = self.public_origin or 'http://' + headers.get('host','')
            if headers.get('origin') and headers['origin'] != expected_origin:
                raise AppError('Cross-origin requests are disabled.',403)
            if not headers.get('content-type','').split(';')[0].strip().lower() == 'application/json':
                raise AppError('Use application/json.',415)
            if not self.limiter.allow((ip,'writes'),120):
                raise AppError('Too many changes. Try again in a minute.',429)
            if not 0 < len(body) <= 8192:
                raise AppError('Invalid request size.')
            data = json.loads(body)
            if not isinstance(data,dict):
                raise AppError('Expected a JSON object.')
            if path == '/api/sessions':
                if not self.limiter.allow((ip,'create'),10):
                    raise AppError('Too many new sessions. Try again in a minute.',429)
                result = self.app.create(**data)
            elif path.startswith('/api/admin/sessions/') and len(path.split('/')) == 6 and path.endswith('/end'):
                if not self.limiter.allow((ip,'owner'),10):
                    raise AppError('Too many owner requests. Try again in a minute.',429)
                token = headers.get('authorization','').removeprefix('Bearer ')
                result = self.app.force_end(path.split('/')[4],token)
            elif path.startswith('/api/sessions/') and len(path.split('/')) == 5:
                _, _, _, sid, action = path.split('/')
                if 'token' in data:
                    raise AppError('Pass credentials in the Authorization header.')
                token = headers.get('authorization','').removeprefix('Bearer ')
                result = self.app.mutate(sid,action,token=token,**data)
            else:
                raise AppError('Not found.',404)
            return self.json(200,result)
        except StorageUnavailable:
            return self.json(503,{'error':'Session storage is unavailable. Refresh before retrying a change.'})
        except AppError as e:
            return self.json(e.status,{'error':str(e)})
        except (ValueError,TypeError,KeyError):
            return self.json(400,{'error':'Invalid request. Check the name, whole-number courts and minutes.'})

    @staticmethod
    def json(status,data):
        return status, {'Content-Type':'application/json','Cache-Control':'no-store'}, json.dumps(data).encode()

SECURITY_HEADERS = {
    'X-Content-Type-Options':'nosniff',
    'Referrer-Policy':'no-referrer',
    'X-Frame-Options':'DENY',
    'Permissions-Policy':'camera=(), microphone=(), geolocation=()',
    'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}
