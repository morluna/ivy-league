import copy
import json
import tempfile
import threading
import unittest
from collections import Counter
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from pickleball.domain import schedule, validate
from pickleball.application import Sessions, AppError
from pickleball.adapters import MemoryRepository, SQLiteRepository, SnapshotRealtime
from server import Handler

class Clock:
    time = 1000
    def now(self): return self.time

class DomainTests(unittest.TestCase):
    def test_invariants_and_playing_time(self):
        for n in range(0, 25):
            for courts in (1, 2, 4):
                players = [str(i) for i in range(n)]
                rounds = schedule(players, courts, 20, 'seed')
                counts = Counter({p:0 for p in players})
                for r in rounds:
                    played = [p for m in r['matches'] for team in m['teams'] for p in team]
                    self.assertEqual(len(played), len(set(played)))
                    self.assertEqual(len(played), min(courts,n//4)*4)
                    self.assertEqual(set(played)|set(r['resting']),set(players))
                    self.assertFalse(set(played)&set(r['resting']))
                    counts.update(played)
                    if counts: self.assertLessEqual(max(counts.values())-min(counts.values()),1)
    def test_deterministic(self):
        args=(list('abcdefghijk'),2,12,'seed')
        self.assertEqual(schedule(*args),schedule(*args))
        self.assertNotEqual(schedule(*args),schedule(*args[:-1],'other'))
    def test_four_player_rotations(self):
        rounds=schedule(list('abcd'),1,3,10)
        pairs=[tuple(sorted(t)) for r in rounds for m in r['matches'] for t in m['teams']]
        self.assertEqual(len(set(pairs)),6)
    def test_invalid(self):
        for args in [(0,120,10),(2,5,10),(2,0,1),(2,481,10),(True,10,2),(2,120,1),(1,10,1.5)]:
            with self.assertRaises(ValueError): validate(*args)
        with self.assertRaises(ValueError): schedule(['a','a'],1,1,0)

class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.repo=MemoryRepository();self.app=Sessions(self.repo,self.clock,SnapshotRealtime())
        self.created=self.app.create('Host',2,60,10);self.sid=self.created['session']['id'];self.token=self.created['token']
    def join(self,name): return self.app.mutate(self.sid,'join',name=name)
    def fill(self): return [self.join(n) for n in ('Ada','Bo','Cy','Dee','Eli','Fay','Gia')]
    def act(self,action,**kw): return self.app.mutate(self.sid,action,self.token,**kw)['session']
    def test_minimum_players(self):
        self.assertFalse(self.app.get(self.sid)['rounds'][0]['matches'])
        with self.assertRaises(AppError): self.act('start')
        self.fill();self.assertEqual(self.act('start')['current'],0)
    def test_duplicate_join_retry_and_names(self):
        a=self.join('Ada')
        b=self.app.mutate(self.sid,'join',token=a['token'],name='Ada')
        self.assertEqual(a,b)
        for name in ('ada',' ADA ','Ａｄａ'):
            with self.assertRaises(AppError): self.join(name)
        self.assertEqual(len(self.app.get(self.sid)['players']),2)
    def test_late_join_departure_future_only(self):
        players=self.fill();s=self.act('start');frozen=copy.deepcopy(s['rounds'][0])
        late=self.join('Late');self.assertEqual(late['session']['rounds'][0],frozen)
        departing=players[0]
        s=self.app.mutate(self.sid,'leave',departing['token'])['session']
        self.assertEqual(s['rounds'][0],frozen)
        for r in s['rounds'][1:]:
            ids=[p for m in r['matches'] for t in m['teams'] for p in t]
            self.assertNotIn(departing['player_id'],ids+r['resting'])
        self.assertTrue(any(late['player_id'] in t for r in s['rounds'][1:] for m in r['matches'] for t in m['teams']))
    def test_timer_pause_resume_reconnect(self):
        self.fill();self.act('start');self.clock.time+=40
        s=self.act('pause');self.assertEqual(s['timer']['remaining'],560)
        self.clock.time+=100;self.assertEqual(self.app.get(self.sid)['timer']['remaining'],560)
        s=self.act('resume');self.assertEqual(s['timer']['started_at'],1140)
        reconnected=Sessions(self.repo,self.clock,SnapshotRealtime()).get(self.sid)
        self.assertEqual(reconnected,s)
        self.clock.time+=1000;s=self.act('pause');self.assertEqual(s['timer']['remaining'],0)
        with self.assertRaises(AppError):self.act('resume')
        self.assertEqual(self.act('end')['timer']['state'],'ended')
        self.assertEqual(self.act('start')['current'],1)
    def test_permissions_and_redaction(self):
        a=self.join('Ada')
        for token in (None,'wrong',a['token']):
            for action in ('start','pause','resume','end','settings'):
                with self.assertRaises(AppError) as error:self.app.mutate(self.sid,action,token)
                self.assertEqual(error.exception.status,403)
        with self.assertRaises(AppError):self.app.mutate(self.sid,'leave',a['token'],player_id=self.created['player_id'])
        view=json.dumps(self.app.get(self.sid))
        self.assertNotIn(self.token,view);self.assertNotIn(a['token'],view)
    def test_state_boundaries(self):
        for action in ('pause','resume','end'):
            with self.assertRaises(AppError):self.act(action)
        self.fill();self.act('start')
        with self.assertRaises(AppError):self.act('start')
        with self.assertRaises(AppError):self.act('settings',courts=1,duration=60,length=10)
        for _ in range(6):
            s=self.act('end')
            if s['timer']['state']!='finished':self.act('start')
        with self.assertRaises(AppError):self.join('Too late')
    def test_settings_and_buffer(self):
        s=self.act('settings',courts=3,duration=65,length=10)
        self.assertEqual(len(s['rounds']),6)
        self.assertEqual(s['courts'],3)
    def test_concurrent_duplicate_names(self):
        outcomes=[]
        def join():
            try:self.join('Same');outcomes.append('ok')
            except AppError:outcomes.append('duplicate')
        threads=[threading.Thread(target=join) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(outcomes.count('ok'),1)
    def test_snapshot_cannot_mutate_storage(self):
        s=self.app.get(self.sid);s['players'].clear()
        self.assertEqual(len(self.app.get(self.sid)['players']),1)
    def test_sqlite_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Sessions(SQLiteRepository(tmp+'/s.db'),self.clock,SnapshotRealtime())
            result=app.create('Host');sid=result['session']['id']
            restarted=Sessions(SQLiteRepository(tmp+'/s.db'),self.clock,SnapshotRealtime())
            self.assertEqual(app.get(sid),restarted.get(sid))

class HttpTests(unittest.TestCase):
    def test_http_create_join_reconnect_and_origin(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.app=Sessions(MemoryRepository(),Clock(),SnapshotRealtime())
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def post(path,data,headers={}):
            return urlopen(Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json',**headers}))
        try:
            self.assertEqual(urlopen(base+'/').status,200)
            created=json.load(post('/api/sessions',dict(name='Host')));sid=created['session']['id']
            joined=json.load(post('/api/sessions/'+sid+'/join',dict(name='Guest')))
            snapshot=json.load(urlopen(base+'/api/sessions/'+sid))
            self.assertEqual(snapshot,joined['session'])
            with self.assertRaises(HTTPError) as error:post('/api/sessions/'+sid+'/start',{})
            self.assertEqual(error.exception.code,403)
            with self.assertRaises(HTTPError):post('/api/sessions',dict(name='Bad'),{'Origin':'https://evil.example'})
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
