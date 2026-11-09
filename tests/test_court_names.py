import copy
import tempfile
import unittest
from pickleball.adapters import MemoryRepository, SQLiteRepository, SnapshotRealtime
from pickleball.application import Sessions, AppError
from test_app import Clock

class CourtNameTests(unittest.TestCase):
    def setUp(self):
        self.repo=MemoryRepository();self.app=Sessions(self.repo,Clock(),SnapshotRealtime())
        created=self.app.create('Host');self.sid=created['session']['id'];self.token=created['token']
    def names(self,values):return self.app.mutate(self.sid,'court-names',self.token,names=values)['session']
    def test_defaults_legacy_and_custom_creation(self):
        self.assertEqual(self.app.get(self.sid)['court_names'],['Court 1','Court 2'])
        self.repo.data[self.sid].pop('court_names')
        self.assertEqual(self.app.get(self.sid)['court_names'],['Court 1','Court 2'])
        s=self.app.create('Other',court_names=['Court 7','North'])['session']
        self.assertEqual(s['court_names'],['Court 7','North'])
    def test_rename_preserves_every_assignment_and_timer(self):
        for i in range(7):self.app.mutate(self.sid,'add-player',self.token,name='Player '+str(i))
        self.app.mutate(self.sid,'start',self.token);self.app.mutate(self.sid,'next',self.token)
        before=self.app.get(self.sid)
        after=self.names([' Court 7 ','North Court'])
        self.assertEqual(after['court_names'],['Court 7','North Court'])
        for key in ('rounds','players','timer','current','courts'):
            self.assertEqual(after[key],before[key])
        self.assertEqual(after['revision'],before['revision']+1)
    def test_validation_and_blank_defaults(self):
        self.assertEqual(self.names(['','South'])['court_names'],['Court 1','South'])
        for values in ([],['Only one'],'text',[None,'A'],['A','a'],['Ａ','A'],['x'*41,'B'],['bad\nname','B']):
            with self.assertRaises(AppError):self.names(values)
    def test_permissions_and_closed_session(self):
        guest=self.app.mutate(self.sid,'join',name='Guest')
        for token in (None,'wrong',guest['token']):
            with self.assertRaises(AppError) as error:self.app.mutate(self.sid,'court-names',token,names=['X','Y'])
            self.assertEqual(error.exception.status,403)
        self.app.mutate(self.sid,'end-session',self.token)
        with self.assertRaises(AppError) as error:self.names(['X','Y'])
        self.assertEqual(error.exception.status,409)
    def test_court_count_preserves_names_and_checks_new_duplicates(self):
        self.names(['Court 7','North'])
        s=self.app.mutate(self.sid,'settings',self.token,courts=3,duration=120,length=None)['session']
        self.assertEqual(s['court_names'],['Court 7','North','Court 3'])
        s=self.app.mutate(self.sid,'settings',self.token,courts=1,duration=120,length=None)['session']
        self.assertEqual(s['court_names'],['Court 7'])
        self.names(['Court 2'])
        with self.assertRaises(AppError):self.app.mutate(self.sid,'settings',self.token,courts=2,duration=120,length=None)
        self.assertEqual(self.app.get(self.sid)['courts'],1)
    def test_sqlite_persistence(self):
        self.names(['Court 7','Court 9'])
        with tempfile.TemporaryDirectory() as tmp:
            repo=SQLiteRepository(tmp+'/s.db');raw=self.repo.get(self.sid);raw['revision']=1;repo.save(raw)
            recovered=Sessions(SQLiteRepository(tmp+'/s.db'),Clock(),SnapshotRealtime()).get(self.sid)
            self.assertEqual(recovered['court_names'],['Court 7','Court 9'])
