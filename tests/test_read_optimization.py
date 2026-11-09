import copy
import json
import io
import threading
import unittest
from pickleball.adapters import MemoryRepository, SnapshotRealtime
from pickleball.application import Sessions, AppError
from pickleball.http import Gateway
from pickleball.ports import RepositoryConflict, StorageUnavailable
from test_app import Clock
from wsgi import create_app

class CountingRepository(MemoryRepository):
    def __init__(self):super().__init__();self.reads=0;self.fail=False
    def get(self,key):
        self.reads+=1
        if self.fail:raise StorageUnavailable('private')
        return super().get(key)

class ReadOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.repo=CountingRepository();self.clock=Clock();self.time=0
        self.now=lambda:self.time
        self.app=Sessions(self.repo,self.clock,SnapshotRealtime(),read_cache_seconds=3,monotonic=self.now)
        created=self.app.create('Host');self.sid=created['session']['id'];self.token=created['token']
    def test_twelve_viewers_share_one_read_after_expiry(self):
        self.time=4;views=[]
        threads=[threading.Thread(target=lambda:views.append(self.app.get(self.sid))) for _ in range(12)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(views),12);self.assertEqual(self.repo.reads,1)
        self.clock.time+=1
        self.assertEqual(self.app.get(self.sid)['server_now'],self.clock.now())
        self.assertEqual(self.repo.reads,1)
        views[0]['players'].clear()
        self.assertEqual(len(self.app.get(self.sid)['players']),1)
        self.time=7;self.app.get(self.sid);self.assertEqual(self.repo.reads,2)
    def test_writes_bypass_cache_and_refresh_view_immediately(self):
        # A different process changes storage while our public read cache is warm.
        other=Sessions(self.repo,self.clock,SnapshotRealtime())
        other.mutate(self.sid,'join',name='Other')
        self.app.mutate(self.sid,'join',name='New')
        self.assertEqual(len(self.app.get(self.sid)['players']),3)
        self.app.mutate(self.sid,'end-session',self.token)
        self.assertEqual(self.app.get(self.sid)['status'],'closed')
        with self.assertRaises(AppError):self.app.mutate(self.sid,'join',name='Late')
    def test_other_process_change_visible_after_ttl(self):
        other=Sessions(self.repo,self.clock,SnapshotRealtime())
        other.mutate(self.sid,'end-session',self.token)
        self.assertEqual(self.app.get(self.sid)['status'],'open')
        self.time=3
        self.assertEqual(self.app.get(self.sid)['status'],'closed')
    def test_expired_cache_does_not_mask_failure(self):
        self.repo.fail=True
        self.time=3
        with self.assertRaises(StorageUnavailable):self.app.get(self.sid)
        self.assertNotIn(self.sid,self.app.read_cache)
    def test_cache_eviction_and_conflict_invalidation(self):
        for i in range(130):self.app.create('Host')
        self.assertEqual(len(self.app.read_cache),128)
        self.assertNotIn(self.sid,self.app.read_cache)
        s=self.repo.get(self.sid);self.app._remember(s)
        s['revision']+=1;self.repo.save(s)
        stale=copy.deepcopy(s);stale['revision']-=1
        with self.assertRaises(AppError):self.app._save(stale)
        self.assertNotIn(self.sid,self.app.read_cache)
    def test_conditional_read_omits_unchanged_payload(self):
        gateway=Gateway(self.app,monotonic=self.now)
        path='/api/sessions/'+self.sid
        status,headers,body=gateway.handle('GET',path,{})
        self.assertEqual(status,200);self.assertTrue(body)
        etag=headers['ETag'];self.clock.time+=1
        status,headers,body=gateway.handle('GET',path,{'if-none-match':etag})
        self.assertEqual(status,304);self.assertEqual(body,b'')
        self.assertEqual(float(headers['X-Server-Time']),self.clock.now())
        self.app.mutate(self.sid,'join',name='New')
        status,headers,body=gateway.handle('GET',path,{'if-none-match':etag})
        self.assertEqual(status,200);self.assertNotEqual(headers['ETag'],etag)
        self.assertEqual(len(json.loads(body)['players']),2)
    def test_health_probe_caches_success_and_recovers_after_failure(self):
        gateway=Gateway(self.app,monotonic=self.now)
        for _ in range(12):self.assertEqual(gateway.handle('GET','/healthz',{})[0],200)
        self.assertEqual(self.repo.reads,1)
        self.repo.fail=True;self.time=29
        self.assertEqual(gateway.handle('GET','/healthz',{})[0],200)
        self.time=30;self.assertEqual(gateway.handle('GET','/healthz',{})[0],503)
        self.assertEqual(self.repo.reads,2)
        self.repo.fail=False;self.time=34
        self.assertEqual(gateway.handle('GET','/healthz',{})[0],503)
        self.time=35;self.assertEqual(gateway.handle('GET','/healthz',{})[0],200)
        self.assertEqual(self.repo.reads,3)

    def test_wsgi_304_has_no_body_or_false_content_length(self):
        wsgi=create_app(self.repo,'https://rally.example');captured={}
        def start(status,headers):captured.update(status=status,headers=dict(headers))
        result=b''.join(wsgi({'REQUEST_METHOD':'GET','PATH_INFO':'/api/sessions/'+self.sid,
            'HTTP_IF_NONE_MATCH':'"r1"','wsgi.input':io.BytesIO()},start))
        self.assertEqual(captured['status'],'304 Not Modified')
        self.assertNotIn('Content-Length',captured['headers'])
        self.assertEqual(result,b'')
