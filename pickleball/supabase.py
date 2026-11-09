"""Server-only Supabase Data API adapter. No SDK or browser credentials needed."""
import json
import socket
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .ports import RepositoryConflict, StorageUnavailable

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the API secret to a redirect target.
        return None

class SupabaseRepository:
    def __init__(self, url, secret, timeout=5, opener=None):
        parsed = urlparse(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('','/') or parsed.query or parsed.fragment):
            raise ValueError('SUPABASE_URL must be an HTTPS project origin.')
        if not isinstance(secret,str) or not secret.startswith('sb_secret_') or any(c.isspace() for c in secret):
            raise ValueError('Set SUPABASE_SECRET_KEY to a server-side sb_secret_ key.')
        self.url, self.secret, self.timeout = url.rstrip('/'), secret, timeout
        self.opener = opener or build_opener(NoRedirect())

    def _request(self, path, data=None):
        payload = None if data is None else json.dumps(data).encode()
        request = Request(self.url+'/rest/v1/'+path,data=payload,headers={
            'apikey':self.secret, 'Content-Type':'application/json', 'Accept':'application/json'
        },method='GET' if data is None else 'POST')
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError()
                return json.loads(raw)
        except (HTTPError,URLError,TimeoutError,socket.timeout,OSError,HTTPException,ValueError) as error:
            # Never echo provider payloads, URLs or headers (which could contain secrets).
            raise StorageUnavailable('Session storage is unavailable. Refresh before retrying a change.') from None

    def get(self, session_id):
        result = self._request('rally_sessions?'+urlencode({'id':'eq.'+session_id,'select':'body','limit':1}))
        if not isinstance(result,list) or len(result)>1:
            raise StorageUnavailable('Invalid storage response.')
        if not result:
            return None
        try:
            body = result[0]['body']
            if not isinstance(body,dict) or body['id'] != session_id or type(body['revision']) is not int:
                raise ValueError()
            return body
        except (KeyError,TypeError,ValueError):
            raise StorageUnavailable('Invalid storage response.') from None

    def save(self, session, expected_revision=None):
        expected = session['revision']-1 if expected_revision is None else expected_revision
        result = self._request('rpc/rally_save_session',{'p_body':session,'p_expected_revision':expected})
        if result is False:
            raise RepositoryConflict()
        if result is not True:
            raise StorageUnavailable('Invalid storage response.')
