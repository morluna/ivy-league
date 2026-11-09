import copy
import tempfile
import unittest
from collections import Counter
from pickleball.domain import schedule, validate
from pickleball.adapters import MemoryRepository, SQLiteRepository, SnapshotRealtime
from pickleball.application import Sessions, AppError
from test_app import Clock

class SinglesDomainTests(unittest.TestCase):
    def test_invariants_fairness_and_reproducibility(self):
        for n in range(26):
            for courts in (1,2,6):
                players=[str(i) for i in range(n)]
                args=dict(players=players,courts=courts,rounds=24,seed='singles',play_format='singles')
                rounds=schedule(**args)
                self.assertEqual(rounds,schedule(**args))
                counts=Counter({p:0 for p in players})
                for r in rounds:
                    played=[p for m in r['matches'] for team in m['teams'] for p in team]
                    self.assertEqual(len(played),min(courts,n//2)*2)
                    self.assertEqual(len(played),len(set(played)))
                    self.assertEqual(set(played)|set(r['resting']),set(players))
                    self.assertFalse(set(played)&set(r['resting']))
                    for m in r['matches']:self.assertEqual([len(t) for t in m['teams']],[1,1])
                    counts.update(played)
                    if counts:self.assertLessEqual(max(counts.values())-min(counts.values()),1)
    def test_opponent_diversity_and_validation(self):
        rounds=schedule(list('abcd'),2,3,'opponents',play_format='singles')
        pairs=[tuple(sorted(m['teams'][0]+m['teams'][1])) for r in rounds for m in r['matches']]
        self.assertEqual(len(set(pairs)),6)
        for bad in (None,'triple','Singles',0,True,[]):
            with self.assertRaises(ValueError):validate(1,120,None,bad)
            with self.assertRaises(ValueError):schedule(['a','b'],1,2,0,play_format=bad)

class SinglesSessionTests(unittest.TestCase):
    def setUp(self):
        self.repo=MemoryRepository();self.clock=Clock();self.app=Sessions(self.repo,self.clock,SnapshotRealtime())
        created=self.app.create('Host',courts=2,play_format='singles')
        self.sid=created['session']['id'];self.token=created['token']
    def act(self,action,**data):return self.app.mutate(self.sid,action,self.token,**data)['session']
    def test_minimum_two_for_manual_play_and_less_than_two_blocks_next(self):
        with self.assertRaises(AppError) as error:self.act('start')
        self.assertIn('2 active players',str(error.exception))
        guest=self.app.mutate(self.sid,'join',name='Guest')
        s=self.act('start');self.assertEqual(len(s['rounds'][0]['matches']),1)
        self.clock.time+=35;self.assertEqual(self.act('next')['current'],1)
        self.act('leave',player_id=guest['player_id']);before=self.app.get(self.sid)
        with self.assertRaises(AppError):self.act('next')
        self.assertEqual(self.app.get(self.sid),before)
        self.act('add-player',name='Guest');self.assertEqual(self.act('next')['current'],2)
    def test_timed_singles_and_organizer_permissions(self):
        self.act('settings',courts=1,duration=20,length=5)
        guest=self.app.mutate(self.sid,'join',name='Guest')
        self.assertEqual(self.app.get(self.sid)['play_format'],'singles')
        self.act('start');self.clock.time+=120
        self.assertEqual(self.act('pause')['timer']['remaining'],180)
        self.act('resume');self.act('end')
        for action in ('start','settings'):
            with self.assertRaises(AppError) as error:self.app.mutate(self.sid,action,guest['token'],courts=1,duration=20,length=5,play_format='doubles')
            self.assertEqual(error.exception.status,403)
    def test_format_switch_before_start_only_and_legacy_doubles(self):
        self.act('add-player',name='Guest')
        self.act('settings',courts=2,duration=120,length=None,play_format='doubles')
        self.assertFalse(self.app.get(self.sid)['rounds'][0]['matches'])
        with self.assertRaises(AppError):self.act('start')
        self.act('settings',courts=2,duration=120,length=None,play_format='singles')
        self.act('start');before=self.app.get(self.sid)
        with self.assertRaises(AppError):self.act('settings',courts=2,duration=120,length=None,play_format='doubles')
        self.assertEqual(self.app.get(self.sid),before)
        old=self.app.create('Legacy');oldid=old['session']['id'];self.repo.data[oldid].pop('play_format')
        self.assertEqual(self.app.get(oldid)['play_format'],'doubles')
        with self.assertRaises(AppError):self.app.mutate(oldid,'start',old['token'])
    def test_roster_changes_preserve_started_singles_rounds_and_clock(self):
        for name in ('A','B','C','D'):self.act('add-player',name=name)
        self.act('start');self.act('next');before=self.app.get(self.sid)
        leaving=before['rounds'][1]['matches'][0]['teams'][0][0]
        self.act('leave',player_id=leaving)
        after=self.act('add-player',name='Late')
        self.assertEqual(after['rounds'][:2],before['rounds'][:2])
        self.assertEqual(after['timer'],before['timer'])
        for r in after['rounds'][2:]:
            self.assertNotIn(leaving,[p for m in r['matches'] for t in m['teams'] for p in t]+r['resting'])
            for m in r['matches']:self.assertEqual([len(t) for t in m['teams']],[1,1])
    def test_preview_extension_and_sqlite_persistence(self):
        self.act('add-player',name='Guest');self.act('start')
        for _ in range(12):s=self.act('next')
        self.assertEqual(s['current'],12)
        self.assertEqual([len(t) for t in s['rounds'][12]['matches'][0]['teams']],[1,1])
        with tempfile.TemporaryDirectory() as tmp:
            repo=SQLiteRepository(tmp+'/s.db');raw=self.repo.get(self.sid);raw['revision']=1;repo.save(raw)
            view=Sessions(SQLiteRepository(tmp+'/s.db'),self.clock,SnapshotRealtime()).get(self.sid)
            self.assertEqual(view['play_format'],'singles');self.assertEqual(view['rounds'],raw['rounds'])
