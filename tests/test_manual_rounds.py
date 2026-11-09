import copy
import tempfile
import unittest
from pickleball.domain import validate
from pickleball.adapters import MemoryRepository, SQLiteRepository, SnapshotRealtime
from pickleball.application import Sessions, AppError
from test_app import Clock

class ManualRoundTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.repo=MemoryRepository()
        self.app=Sessions(self.repo,self.clock,SnapshotRealtime())
        created=self.app.create('Host',courts=1)
        self.sid=created['session']['id'];self.token=created['token']
        self.guests=[self.app.mutate(self.sid,'join',name=name) for name in ('A','B','C')]
    def act(self,action,**data):return self.app.mutate(self.sid,action,self.token,**data)['session']
    def test_optional_validation_and_initial_preview(self):
        validate(2,120,None)
        s=self.app.get(self.sid)
        self.assertIsNone(s['length']);self.assertIsNone(s['timer']['remaining'])
        self.assertEqual(len(s['rounds']),12)
        for bad in (0,-1,1.5,True,'',False):
            with self.assertRaises(ValueError):validate(1,120,bad)
    def test_countup_reconnect_and_atomic_next(self):
        first=self.act('start');started=first['timer']['started_at']
        self.clock.time+=137
        reconnected=Sessions(self.repo,self.clock,SnapshotRealtime()).get(self.sid)
        self.assertEqual(reconnected['server_now']-reconnected['timer']['started_at'],137)
        self.assertIsNone(reconnected['timer']['remaining'])
        s=self.act('next')
        self.assertEqual(s['current'],1)
        self.assertEqual(s['rounds'][0],first['rounds'][0])
        self.assertEqual(s['timer']['started_at'],self.clock.now())
        self.assertEqual(s['timer']['elapsed'],0)
        self.assertNotEqual(started,s['timer']['started_at'])
    def test_roster_changes_preserve_clock_and_started_rounds(self):
        self.act('start');self.act('next');before=self.app.get(self.sid)
        self.clock.time+=45
        self.act('add-player',name='Late')
        after=self.act('leave',player_id=self.guests[0]['player_id'])
        self.assertEqual(after['rounds'][:2],before['rounds'][:2])
        self.assertEqual(after['timer'],before['timer'])
    def test_failed_advance_preserves_active_round(self):
        self.act('start');self.act('leave',player_id=self.guests[0]['player_id'])
        before=self.app.get(self.sid)
        with self.assertRaises(AppError):self.act('next')
        self.assertEqual(self.app.get(self.sid),before)
    def test_permissions_and_mode_specific_actions(self):
        with self.assertRaises(AppError):self.act('next')
        self.act('start');before=self.app.get(self.sid)
        for token in (None,'wrong',self.guests[0]['token']):
            with self.assertRaises(AppError) as error:self.app.mutate(self.sid,'next',token)
            self.assertEqual(error.exception.status,403)
        for action in ('pause','resume'):
            with self.assertRaises(AppError):self.act(action)
        self.assertEqual(self.app.get(self.sid),before)
        other=self.app.create('Timed',length=10)
        with self.assertRaises(AppError):self.app.mutate(other['session']['id'],'next',other['token'])
    def test_extends_preview_without_rewriting_rounds_and_stays_bounded(self):
        initial=self.app.get(self.sid)['rounds']
        self.act('start')
        for _ in range(12):s=self.act('next')
        self.assertEqual(s['current'],12);self.assertEqual(len(s['rounds']),13)
        self.assertEqual(s['rounds'][:12],initial)
        for _ in range(83):s=self.act('next')
        self.assertEqual(s['current'],95);self.assertEqual(len(s['rounds']),96)
        before=self.app.get(self.sid)
        with self.assertRaises(AppError):self.act('next')
        self.assertEqual(self.app.get(self.sid),before)
        self.assertEqual(self.act('end-session')['status'],'closed')
    def test_end_stops_countup_without_automatic_session_expiry(self):
        self.act('start');self.clock.time+=20000
        self.assertEqual(self.app.get(self.sid)['status'],'open')
        ended=self.act('end')
        self.assertEqual(ended['timer']['elapsed'],20000)
        self.assertEqual(ended['timer']['state'],'ended')
        started=self.act('start');self.assertEqual(started['timer']['elapsed'],0)
        self.clock.time+=33
        closed=self.act('end-session')
        self.assertEqual(closed['timer']['elapsed'],33)
        self.assertIsNone(closed['timer']['started_at'])
        self.clock.time+=100
        self.assertEqual(self.app.get(self.sid)['timer'],closed['timer'])
        with self.assertRaises(AppError):self.act('next')
    def test_switch_modes_before_start_and_sqlite_restart(self):
        self.assertEqual(self.act('settings',courts=1,duration=120,length=10)['length'],10)
        self.assertIsNone(self.act('settings',courts=1,duration=120,length=None)['length'])
        self.act('start')
        with self.assertRaises(AppError):self.act('settings',courts=1,duration=120,length=10)
        with tempfile.TemporaryDirectory() as tmp:
            repo=SQLiteRepository(tmp+'/s.db');raw=self.repo.get(self.sid);raw['revision']=1;repo.save(raw)
            recovered=Sessions(SQLiteRepository(tmp+'/s.db'),self.clock,SnapshotRealtime()).get(self.sid)
            self.assertEqual(recovered['timer'],raw['timer'])
            self.assertIsNone(recovered['length'])
