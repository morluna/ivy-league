"""Single-process production entry point; PUBLIC_ORIGIN is mandatory."""
import os
from http import HTTPStatus
from pathlib import Path
from pickleball.application import Sessions
from pickleball.adapters import SQLiteRepository, SystemClock, SnapshotRealtime
from pickleball.http import Gateway, SECURITY_HEADERS


def create_app(repository=None, public_origin=None):
    origin = public_origin or os.environ.get('PUBLIC_ORIGIN')
    if not origin:
        raise ValueError('Set PUBLIC_ORIGIN to the public HTTPS address before starting production.')
    if repository is None:
        path = Path(os.environ.get('DATABASE_PATH','/data/sessions.sqlite3'))
        path.parent.mkdir(parents=True,exist_ok=True)
        repository = SQLiteRepository(str(path))
    gateway = Gateway(Sessions(repository,SystemClock(),SnapshotRealtime()),origin)
    def application(environ,start_response):
        headers = {k[5:].lower().replace('_','-'):v for k,v in environ.items() if k.startswith('HTTP_')}
        headers['content-type'] = environ.get('CONTENT_TYPE','')
        try:
            size = int(environ.get('CONTENT_LENGTH') or 0)
            if size < 0 or size > 8192:
                raise ValueError()
            body = environ['wsgi.input'].read(size) if environ['REQUEST_METHOD'] == 'POST' else b''
            status, response_headers, payload = gateway.handle(environ['REQUEST_METHOD'],environ.get('PATH_INFO','/'),headers,body,environ.get('REMOTE_ADDR','proxy'))
        except ValueError:
            status, response_headers, payload = gateway.json(400,{'error':'Invalid request size.'})
        except Exception:
            # Avoid leaking database paths or credential-bearing state to clients.
            status, response_headers, payload = gateway.json(500,{'error':'The server could not complete this request.'})
        response_headers = {**SECURITY_HEADERS,**response_headers,'Content-Length':str(len(payload)), 'Strict-Transport-Security':'max-age=31536000'}
        start_response('%s %s' % (status,HTTPStatus(status).phrase),list(response_headers.items()))
        return [payload]
    return application
