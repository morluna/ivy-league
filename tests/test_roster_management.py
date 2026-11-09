import copy
import json
import unittest
from pickleball.adapters import MemoryRepository, SnapshotRealtime
from pickleball.application import Sessions, AppError
from test_app import Clock

class OrganizerRosterTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.repo=MemoryRepository()
        self.app=Sessions(self.repo,self.clock,SnapshotRealtime())
        created=self.app.create('Host',2,120,10)
        self.sid=created['session']['id'];self.token=created['token']
        self.guests=[self.app.mutate(self.sid,'join',name='Player '+str(i)) for i in range(1,12)]
    def act(self,action,**data):return self.app.mutate(self.sid,action,self.token,**data)
    def test_organizer_add_does_not_replace_identity(self):
        added=self.act('add-player',name='New Player')
        self.assertEqual(set(added),{'session'})
        self.assertEqual(len(added['session']['players']),13)
        self.assertNotIn('token',json.dumps(added))
        self.assertEqual(self.act('start')['session']['current'],0)
    def test_add_permissions_validation_and_duplicates(self):
        for token in (None,'wrong',self.guests[0]['token']):
            with self.assertRaises(AppError) as error:self.app.mutate(self.sid,'add-player',token,name='Other')
            self.assertEqual(error.exception.status,403)
        for name in ('',' ','x'*41,'bad\nname'):
            with self.assertRaises(AppError):self.act('add-player',name=name)
        for name in ('host',' Ｈｏｓｔ '):
            with self.assertRaises(AppError) as error:self.act('add-player',name=name)
            self.assertEqual(error.exception.status,409)
    def test_removal_and_restore_keep_completed_and_active_rounds(self):
        self.act('start');self.act('end');self.act('start')
        initial=self.app.get(self.sid)
        frozen=copy.deepcopy(initial['rounds'][:2]);timer=copy.deepcopy(initial['timer'])
        # Remove someone assigned to the active round, not just a resting player.
        departing=initial['rounds'][1]['matches'][0]['teams'][0][0]
        changed=self.act('leave',player_id=departing)['session']
        self.assertEqual(changed['rounds'][:2],frozen)
        self.assertEqual(changed['timer'],timer)
        self.assertNotEqual(changed['rounds'][2:],initial['rounds'][2:])
        for r in changed['rounds'][2:]:
            self.assertNotIn(departing,[p for m in r['matches'] for t in m['teams'] for p in t]+r['resting'])
        changed=self.act('add-player',name='Late Player')['session']
        late=next(p['id'] for p in changed['players'] if p['name']=='Late Player')
        self.assertEqual(changed['rounds'][:2],frozen);self.assertEqual(changed['timer'],timer)
        self.assertTrue(any(late in t for r in changed['rounds'][2:] for m in r['matches'] for t in m['teams']))
        old_player=next(p for p in changed['players'] if p['id']==departing)
        restored=self.act('add-player',name=old_player['name'])['session']
        self.assertEqual(restored['rounds'][:2],frozen)
        self.assertEqual(len(restored['players']),13)
        self.assertTrue(next(p['active'] for p in restored['players'] if p['id']==departing))
        self.assertTrue(any(departing in t for r in restored['rounds'][2:] for m in r['matches'] for t in m['teams']))
    def test_round_freezing_in_all_lifecycle_states(self):
        baseline=self.repo.get(self.sid)
        for state in ('idle','running','paused','expired','ended'):
            with self.subTest(state=state):
                self.repo.data[self.sid]=copy.deepcopy(baseline)
                if state!='idle':
                    self.act('start');self.act('end');self.act('start')
                if state=='paused':self.act('pause')
                if state=='expired':self.clock.time+=1000
                if state=='ended':self.act('end')
                before=self.app.get(self.sid);count=before['current']+1
                removed=self.act('leave',player_id=self.guests[0]['player_id'])['session']
                added=self.act('add-player',name='Added')['session']
                for after in (removed,added):
                    self.assertEqual(after['rounds'][:count],before['rounds'][:count])
                    self.assertEqual(after['timer'],before['timer'])
                    self.assertEqual(after['current'],before['current'])
    def test_closed_session_cannot_add_or_restore(self):
        self.act('leave',player_id=self.guests[0]['player_id']);self.act('end-session')
        before=self.app.get(self.sid)
        for name in ('New',before['players'][1]['name']):
            with self.assertRaises(AppError) as error:self.act('add-player',name=name)
            self.assertEqual(error.exception.status,409)
        self.assertEqual(self.app.get(self.sid),before)
    def test_restore_preserves_existing_participant_access(self):
        guest=self.guests[0]
        self.act('leave',player_id=guest['player_id'])
        self.act('add-player',name=guest['session']['players'][-1]['name'])
        # Existing participant capability remains valid after restoration.
        s=self.app.mutate(self.sid,'leave',guest['token'])['session']
        self.assertFalse(next(p['active'] for p in s['players'] if p['id']==guest['player_id']))
