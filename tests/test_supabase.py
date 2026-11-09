"""Offline provider contract tests: transport, compare-and-swap, and use cases."""
import copy
import io
import json
import tempfile
import threading
from http.client import IncompleteRead
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
from pickleball.adapters import MemoryRepository, SQLiteRepository, SnapshotRealtime, repository_from_environment
from pickleball.application import Sessions, AppError
from pickleball.http import Gateway
from pickleball.ports import RepositoryConflict, StorageUnavailable
from pickleball.supabase import SupabaseRepository, NoRedirect
from test_app import Clock
from wsgi import create_app

class Response(io.BytesIO):
    pass

class Provider:
    """Models the documented REST endpoints, not a replacement for live SQL testing."""
    def __init__(self):
        self.rows={};self.requests=[];self.lock=threading.Lock();self.barrier=None
    def open(self,request,timeout):
        with self.lock:
            self.requests.append((request,timeout))
            if request.get_method() == 'GET':
                sid=parse_qs(urlparse(request.full_url).query)['id'][0][3:]
                result=[{'body':copy.deepcopy(self.rows[sid])}] if sid in self.rows else []
            else:
                payload=json.loads(request.data);body=payload['p_body'];expected=payload['p_expected_revision']
                current=self.rows.get(body['id'])
                result=(current['revision'] if current else 0)==expected
                if result:self.rows[body['id']]=copy.deepcopy(body)
        if request.get_method()=='GET' and self.barrier:self.barrier.wait(timeout=5)
        return Response(json.dumps(result).encode())

class SupabaseTests(unittest.TestCase):
    def setUp(self):
        self.provider=Provider()
        self.repo=SupabaseRepository('https://test.supabase.co','sb_secret_TEST_ONLY',opener=self.provider)
        self.app=Sessions(self.repo,Clock(),SnapshotRealtime())
    def test_create_join_timer_and_restart(self):
        result=self.app.create('Host');sid=result['session']['id'];token=result['token']
        self.assertNotIn(token,json.dumps(self.provider.rows))
        for name in ('A','B','C'):self.app.mutate(sid,'join',name=name)
        self.app.mutate(sid,'start',token)
        self.app.clock.time+=20
        paused=self.app.mutate(sid,'pause',token)['session']
        self.assertEqual(paused['timer']['remaining'],580)
        restarted=Sessions(SupabaseRepository('https://test.supabase.co','sb_secret_TEST_ONLY',opener=self.provider),self.app.clock,SnapshotRealtime())
        self.assertEqual(restarted.get(sid),paused)
        restarted.mutate(sid,'resume',token)
        with self.assertRaises(AppError):restarted.mutate(sid,'end','wrong')
        for request,timeout in self.provider.requests:
            self.assertEqual(request.get_header('Apikey'),'sb_secret_TEST_ONLY')
            self.assertIsNone(request.get_header('Authorization'))
            self.assertEqual(timeout,5)
    def test_conflicting_writers_preserve_winner_and_allow_retry(self):
        sid=self.app.create('Host')['session']['id']
        second=Sessions(self.repo,Clock(),SnapshotRealtime())
        self.provider.barrier=threading.Barrier(2)
        outcomes=[]
        def join(app,name):
            try:app.mutate(sid,'join',name=name);outcomes.append(('ok',name))
            except AppError as error:outcomes.append((error.status,name))
        threads=[threading.Thread(target=join,args=(app,name)) for app,name in ((self.app,'A'),(second,'B'))]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.provider.barrier=None
        self.assertEqual(sorted(str(status) for status,_ in outcomes),['409','ok'])
        self.assertEqual(len(self.app.get(sid)['players']),2)
        loser=next(name for status,name in outcomes if status==409)
        self.app.mutate(sid,'join',name=loser)
        self.assertEqual(len(self.app.get(sid)['players']),3)
    def test_owner_closure_persists_and_rejects_stale_writer(self):
        key='test-owner-key-for-cloud-closure-123456789'
        owner=Sessions(self.repo,Clock(),SnapshotRealtime(),admin_key=key)
        created=owner.create('Host');sid=created['session']['id']
        stale=self.repo.get(sid);stale['revision']+=1
        closed=owner.force_end(sid,key)['session']
        with self.assertRaises(RepositoryConflict):self.repo.save(stale,expected_revision=1)
        restarted=Sessions(self.repo,owner.clock,SnapshotRealtime(),admin_key=key)
        self.assertEqual(restarted.get(sid),closed)
        with self.assertRaises(AppError) as error:restarted.mutate(sid,'join',name='Late')
        self.assertEqual(error.exception.status,409)

    def test_query_encoding_missing_and_no_redirects(self):
        self.assertIsNone(self.repo.get('x&select=organizer_token'))
        query=parse_qs(urlparse(self.provider.requests[-1][0].full_url).query)
        self.assertEqual(query['id'],['eq.x&select=organizer_token'])
        self.assertEqual(query['select'],['body'])
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example'))
    def test_failures_are_private_and_not_retried(self):
        class Failure:
            count=0
            def open(self,request,timeout):
                self.count+=1
                raise HTTPError(request.full_url,503,'secret-provider-details',{},io.BytesIO(b'sb_secret_TEST_ONLY'))
        failure=Failure();self.repo.opener=failure
        with self.assertRaises(StorageUnavailable) as error:self.repo.save({'id':'x','revision':1})
        self.assertEqual(failure.count,1)
        self.assertNotIn('sb_secret',str(error.exception))
        self.assertNotIn('secret-provider',str(error.exception))
        gateway=Gateway(self.app)
        self.assertEqual(gateway.handle('GET','/api/sessions/x',{})[0],503)
        self.assertEqual(gateway.handle('GET','/healthz',{})[0],503)
        for exception in (TimeoutError('private'),URLError('private'),OSError('private'),IncompleteRead(b'private')):
            with patch.object(failure,'open',side_effect=exception):
                with self.assertRaises(StorageUnavailable):self.repo.get('x')
    def test_invalid_responses(self):
        class Result:
            def __init__(self,body):self.body=body
            def open(self,*args,**kwargs):return Response(self.body)
        for body in (b'not json',b'{}',b'null',b'[{}]',b'[{"body":{"id":"wrong","revision":1}}]',b'x'*2_000_001):
            self.repo.opener=Result(body)
            with self.assertRaises(StorageUnavailable):self.repo.get('x')
        for body in (b'null',b'{}',b'1'):
            self.repo.opener=Result(body)
            with self.assertRaises(StorageUnavailable):self.repo.save({'id':'x','revision':1})
    def test_configuration_no_fallback(self):
        for url in ('http://example.com','https://user:pass@example.com','https://example.com/path','https://example.com?x=y'):
            with self.assertRaises(ValueError):SupabaseRepository(url,'sb_secret_TEST')
        for key in ('','sb_publishable_TEST','legacy-jwt','sb_secret_test\n'):
            with self.assertRaises(ValueError):SupabaseRepository('https://example.com',key)
        with patch.dict('os.environ',{'STORAGE_BACKEND':'supabase','SUPABASE_URL':'','SUPABASE_SECRET_KEY':''},clear=True):
            with self.assertRaises(ValueError):repository_from_environment('/tmp/unused-rally.sqlite3')
        with patch.dict('os.environ',{'STORAGE_BACKEND':'typo'},clear=True):
            with self.assertRaises(ValueError):repository_from_environment('/tmp/unused-rally.sqlite3')
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{},clear=True):
            self.assertIsInstance(repository_from_environment(tmp+'/local.db'),SQLiteRepository)
    def test_render_origin_and_wsgi_storage_selection(self):
        with patch.dict('os.environ',{'RENDER_EXTERNAL_URL':'https://rally.onrender.com'},clear=True):
            self.assertTrue(callable(create_app(self.repo)))
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(ValueError):create_app(self.repo)
        with patch.dict('os.environ',{'PUBLIC_ORIGIN':'https://rally.example','STORAGE_BACKEND':'supabase'},clear=True):
            with self.assertRaises(ValueError):create_app()

    def test_local_adapters_reject_stale_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            for repo in (MemoryRepository(),SQLiteRepository(tmp+'/test.db'),self.repo):
                app=Sessions(repo,Clock(),SnapshotRealtime());sid=app.create('Host')['session']['id']
                first,second=repo.get(sid),repo.get(sid)
                first['revision']+=1;second['revision']+=1
                repo.save(first,expected_revision=1)
                with self.assertRaises(RepositoryConflict):repo.save(second,expected_revision=1)
                self.assertEqual(repo.get(sid),first)
