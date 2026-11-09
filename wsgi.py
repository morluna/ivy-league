"""Single-process production entry point; an explicit HTTPS origin is required."""
import os
from http import HTTPStatus
from pickleball.application import Sessions
from pickleball.adapters import repository_from_environment, SystemClock, SnapshotRealtime
from pickleball.http import Gateway, SECURITY_HEADERS


def create_app(repository=None, public_origin=None):
    origin = public_origin or os.environ.get('PUBLIC_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL')
    if not origin:
        raise ValueError('Set PUBLIC_ORIGIN to the public HTTPS address before starting production.')
    if repository is None:
        repository = repository_from_environment('/data/sessions.sqlite3')
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
