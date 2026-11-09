import copy
import json
import tempfile
import unittest
from pickleball.adapters import MemoryRepository, SQLiteRepository, SnapshotRealtime
from pickleball.application import Sessions, AppError
from pickleball.http import Gateway
from test_app import Clock

OWNER_KEY='test-owner-key-for-session-control-123456789'

class SessionEndTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.repo=MemoryRepository()
        self.app=Sessions(self.repo,self.clock,SnapshotRealtime(),admin_key=OWNER_KEY)
        self.created=self.app.create('Host',length=10);self.sid=self.created['session']['id'];self.token=self.created['token']
        self.guest=self.app.mutate(self.sid,'join',name='Guest')
        for name in ('A','B'):self.app.mutate(self.sid,'join',name=name)
    def assert_closed(self,s):
        self.assertEqual(s['status'],'closed');self.assertEqual(s['timer']['state'],'finished')
        self.assertIsNone(s['timer']['started_at']);self.assertEqual(s['timer']['remaining'],0)
        for action in ('join','leave','start','pause','resume','end','settings'):
            with self.assertRaises(AppError) as error:self.app.mutate(self.sid,action,self.token,name='Late',courts=1,duration=60,length=10)
            self.assertEqual(error.exception.status,409)
    def test_organizer_can_end_waiting_running_paused_between_rounds(self):
        initial=self.repo.get(self.sid)
        for state in ('idle','running','paused','ended'):
            with self.subTest(state=state):
                self.repo.data[self.sid]=copy.deepcopy(initial)
                if state!='idle':self.app.mutate(self.sid,'start',self.token)
                if state=='paused':self.app.mutate(self.sid,'pause',self.token)
                if state=='ended':self.app.mutate(self.sid,'end',self.token)
                before=self.app.get(self.sid)
                closed=self.app.mutate(self.sid,'end-session',self.token)['session']
                self.assert_closed(closed)
                self.assertEqual(closed['rounds'],before['rounds'])
                self.assertEqual(closed['players'],before['players'])
                self.assertEqual(closed['closed_by'],'organizer')
                self.assertEqual(closed['closed_at'],self.clock.now())
                again=self.app.mutate(self.sid,'end-session',self.token)['session']
                self.assertEqual(again,closed)
                self.clock.time+=500
                self.assertEqual(self.app.get(self.sid)['timer'],closed['timer'])
    def test_only_organizer_can_use_session_end(self):
        for token in (None,'bad',self.guest['token'],OWNER_KEY):
            with self.assertRaises(AppError) as error:self.app.mutate(self.sid,'end-session',token)
            self.assertEqual(error.exception.status,403)
        self.assertEqual(self.app.get(self.sid)['status'],'open')
    def test_owner_key_separate_and_disabled_by_default(self):
        for token in (None,'bad',self.token,self.guest['token']):
            with self.assertRaises(AppError) as error:self.app.force_end(self.sid,token)
            self.assertEqual(error.exception.status,403)
        disabled=Sessions(self.repo,self.clock,SnapshotRealtime())
        with self.assertRaises(AppError):disabled.force_end(self.sid,OWNER_KEY)
        with self.assertRaises(ValueError):Sessions(self.repo,self.clock,SnapshotRealtime(),admin_key='short')
        closed=self.app.force_end(self.sid,OWNER_KEY)['session']
        self.assert_closed(closed);self.assertEqual(closed['closed_by'],'owner')
        self.assertEqual(self.app.force_end(self.sid,OWNER_KEY)['session'],closed)
        self.assertNotIn(OWNER_KEY,json.dumps(closed))
        with self.assertRaises(AppError) as error:self.app.force_end('missing',OWNER_KEY)
        self.assertEqual(error.exception.status,404)
    def test_http_owner_boundary_and_same_origin(self):
        gateway=Gateway(self.app,'https://rally.example')
        path='/api/admin/sessions/'+self.sid+'/end'
        def end(token,origin='https://rally.example'):
            return gateway.handle('POST',path,{'content-type':'application/json','origin':origin,'authorization':'Bearer '+token},b'{}')
        self.assertEqual(gateway.handle('GET','/admin',{})[0],200)
        self.assertEqual(gateway.handle('GET','/admin.js',{})[0],200)
        self.assertEqual(gateway.handle('GET',path,{})[0],404)
        for token in ('',self.token,self.guest['token']):self.assertEqual(end(token)[0],403)
        self.assertEqual(end(OWNER_KEY,'https://evil.example')[0],403)
        self.assertEqual(end(OWNER_KEY)[0],200)
        self.assertEqual(json.loads(gateway.handle('GET','/api/sessions/'+self.sid,{})[2])['status'],'closed')
    def test_legacy_completed_session_is_read_only(self):
        raw=self.repo.data[self.sid]
        raw['timer'].update(state='finished',remaining=0,started_at=None)
        self.assert_closed(self.app.get(self.sid))
        self.assertEqual(self.app.force_end(self.sid,OWNER_KEY)['session']['revision'],raw['revision'])
    def test_closed_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=SQLiteRepository(tmp+'/test.db')
            raw=self.repo.get(self.sid);raw['revision']=1;repo.save(raw)
            app=Sessions(repo,self.clock,SnapshotRealtime(),admin_key=OWNER_KEY)
            closed=app.force_end(self.sid,OWNER_KEY)['session']
            restarted=Sessions(SQLiteRepository(tmp+'/test.db'),self.clock,SnapshotRealtime(),admin_key=OWNER_KEY)
            self.assertEqual(restarted.get(self.sid),closed)
