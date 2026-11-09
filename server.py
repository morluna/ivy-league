"""Dependency-free local adapter. Use wsgi.py + Gunicorn for the hosted pilot."""
import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from pickleball.application import Sessions
from pickleball.adapters import repository_from_environment, SystemClock, SnapshotRealtime
from pickleball.http import Gateway, SECURITY_HEADERS

ROOT = Path(__file__).resolve().parent

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log session URLs, query strings, or credentials.
        pass

    def dispatch(self):
        if not hasattr(self.server,'gateway'):
            self.server.gateway = Gateway(self.server.app)
        gateway = self.server.gateway
        try:
            size = int(self.headers.get('Content-Length',0))
            if size < 0 or size > 8192:
                raise ValueError()
            body = self.rfile.read(size) if self.command == 'POST' else b''
            status, headers, payload = gateway.handle(self.command,self.path,{k.lower():v for k,v in self.headers.items()},body,self.client_address[0])
        except ValueError:
            status, headers, payload = gateway.json(400,{'error':'Invalid request size.'})
        self.send_response(status)
        response_headers = {**SECURITY_HEADERS,**headers}
        if status != 304:
            response_headers['Content-Length'] = str(len(payload))
        for k,v in response_headers.items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(payload)

    do_GET = dispatch
    do_POST = dispatch
    do_HEAD = dispatch
    do_OPTIONS = dispatch

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', default=str(ROOT / 'sessions.sqlite3'))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host,args.port),Handler)
    server.app = Sessions(repository_from_environment(args.db),SystemClock(),SnapshotRealtime(),admin_key=os.environ.get('SESSION_ADMIN_KEY'),read_cache_seconds=3)
    server.gateway = Gateway(server.app)
    print('Open http://localhost:%s — Ctrl+C to stop' % args.port,flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
