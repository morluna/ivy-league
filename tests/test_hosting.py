import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from pickleball.adapters import MemoryRepository, SQLiteRepository
from pickleball.application import Sessions
from pickleball.http import Gateway
from pickleball.security import RateLimiter
from scripts.backup import backup
from wsgi import create_app
from test_app import Clock
from pickleball.adapters import SnapshotRealtime

class HostingTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.app = Sessions(self.repo,Clock(),SnapshotRealtime())
        self.gateway = Gateway(self.app,'https://rally.example')

    def post(self,path,data,**headers):
        return self.gateway.handle('POST',path,{'content-type':'application/json','origin':'https://rally.example',**headers},json.dumps(data).encode())

    def test_https_origin_and_credentials(self):
        status,_,body = self.post('/api/sessions',dict(name='Host',courts=2,duration=120,length=10))
        self.assertEqual(status,200)
        result=json.loads(body);sid=result['session']['id'];token=result['token']
        stored=json.dumps(self.repo.get(sid))
        self.assertNotIn(token,stored)
        self.assertIn('sha256:',stored)
        self.assertEqual(self.post('/api/sessions/'+sid+'/settings',dict(courts=1,duration=60,length=10),authorization='Bearer '+token)[0],200)
        self.assertEqual(self.post('/api/sessions',dict(name='Other'),origin='https://evil.example')[0],403)
        self.assertEqual(self.post('/api/sessions/'+sid+'/settings',dict(courts=1,duration=60,length=10),authorization='Bearer wrong')[0],403)

    def test_rate_limits_and_recovery(self):
        time=[0]
        limiter=RateLimiter(lambda:time[0]);self.gateway.limiter=limiter
        for i in range(10):self.assertEqual(self.post('/api/sessions',dict(name='Host'))[0],200)
        self.assertEqual(self.post('/api/sessions',dict(name='Host'))[0],429)
        time[0]=61
        self.assertEqual(self.post('/api/sessions',dict(name='Host'))[0],200)
        self.assertTrue(limiter.allow(('another','create'),1))

    def test_validation_and_static_allowlist(self):
        for body in (b'[]',b'{',b'x'*8193):
            self.assertEqual(self.gateway.handle('POST','/api/sessions',{'content-type':'application/json'},body)[0],400)
        self.assertEqual(self.gateway.handle('POST','/api/sessions',{},b'{}')[0],415)
        for path in ('/../sessions.sqlite3','/README.md','/','/style.css','/app.js'):
            self.assertEqual(self.gateway.handle('GET',path,{})[0],200 if path in ('/','/style.css','/app.js') else 404)
        self.assertEqual(self.gateway.handle('GET','/healthz',{})[0],200)

    def test_wsgi_headers_size_and_storage_failure(self):
        wsgi=create_app(self.repo,'https://rally.example')
        def call(path='/',length='',method='GET',body=b''):
            captured={}
            def start(status,headers):captured.update(status=status,headers=dict(headers))
            response=b''.join(wsgi(dict(REQUEST_METHOD=method,PATH_INFO=path,CONTENT_LENGTH=length,CONTENT_TYPE='application/json',HTTP_ORIGIN='https://rally.example',REMOTE_ADDR='test',**{'wsgi.input':io.BytesIO(body)}),start))
            return captured,response
        result,_=call()
        self.assertEqual(result['status'],'200 OK')
        for header in ('Content-Security-Policy','Referrer-Policy','Strict-Transport-Security'):
            self.assertIn(header,result['headers'])
        self.assertTrue(call(length='99999',method='POST')[0]['status'].startswith('400'))
        self.assertTrue(call(length='invalid',method='POST')[0]['status'].startswith('400'))
        for origin in ('http://rally.example','https://rally.example/','https://rally.example/path'):
            with self.assertRaises(ValueError):create_app(self.repo,origin)
        def broken(key):raise RuntimeError('secret database path')
        self.repo.get=broken
        result,body=call('/healthz')
        self.assertTrue(result['status'].startswith('503'))
        self.assertNotIn(b'secret',body)

    def test_legacy_migration_and_consistent_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=tmp+'/s.db';repo=SQLiteRepository(path)
            created=self.app.create('Host');sid=created['session']['id'];raw=created['token']
            legacy=self.repo.get(sid);legacy['organizer_token']=raw;legacy['players'][0]['token']=raw
            repo.save(legacy)
            migrated=SQLiteRepository(path)
            self.assertNotIn(raw,json.dumps(migrated.get(sid)))
            app=Sessions(migrated,Clock(),SnapshotRealtime())
            app.mutate(sid,'settings',raw,courts=1,duration=60,length=10)
            backup(path,tmp+'/backup.db')
            restored=Sessions(SQLiteRepository(tmp+'/backup.db'),Clock(),SnapshotRealtime())
            self.assertEqual(restored.get(sid),app.get(sid))
            with self.assertRaises(ValueError):backup(path,tmp+'/backup.db')
            with self.assertRaises(ValueError):backup(path,path)
            with self.assertRaises(sqlite3.OperationalError):backup(tmp+'/missing.db',tmp+'/empty.db')
