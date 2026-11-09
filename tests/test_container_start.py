import os
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

class ContainerStartupTests(unittest.TestCase):
    def test_root_home_is_replaced_before_starting_gunicorn(self):
        user=SimpleNamespace(pw_uid=10001,pw_gid=10001,pw_dir='/home/rally',pw_name='rally')
        with patch.dict(os.environ,{'HOME':'/root','USER':'root','LOGNAME':'root','STORAGE_BACKEND':'supabase','PORT':'10000'},clear=True), \
             patch('os.getuid',return_value=0), patch('pwd.getpwnam',return_value=user), \
             patch('os.umask'), patch('os.setgroups') as groups, patch('os.setgid') as gid, \
             patch('os.setuid') as uid, patch('os.execvp') as execute, patch('os.chown') as chown:
            runpy.run_path(str(Path(__file__).resolve().parent.parent/'scripts/container_start.py'),run_name='__main__')
            self.assertEqual(os.environ['HOME'],'/home/rally')
            self.assertEqual(os.environ['USER'],'rally')
            self.assertEqual(os.environ['LOGNAME'],'rally')
            groups.assert_called_once_with([])
            gid.assert_called_once_with(10001)
            uid.assert_called_once_with(10001)
            chown.assert_not_called()
            args=execute.call_args[0]
            self.assertEqual(args[0],'gunicorn')
            self.assertIn('0.0.0.0:10000',args[1])
