"""Initialize persistent mount permissions, then permanently drop root before serving."""
import os
import pwd
from pathlib import Path

if __name__ == '__main__':
    os.umask(0o077)
    path = None
    if os.environ.get('STORAGE_BACKEND','sqlite') == 'sqlite':
        path = Path(os.environ.get('DATABASE_PATH','/data/sessions.sqlite3'))
        path.parent.mkdir(parents=True,exist_ok=True)
    if os.getuid() == 0:
        user = pwd.getpwnam('rally')
        if path is not None:
            os.chown(path.parent,user.pw_uid,user.pw_gid)
            if path.exists():
                os.chown(path,user.pw_uid,user.pw_gid)
        # setuid does not update inherited root home/user variables.
        # Gunicorn uses HOME for its control socket directory.
        os.environ.update(HOME=user.pw_dir, USER=user.pw_name, LOGNAME=user.pw_name)
        os.setgroups([])
        os.setgid(user.pw_gid)
        os.setuid(user.pw_uid)
    os.execvp('gunicorn',['gunicorn','wsgi:create_app()','--bind','0.0.0.0:'+os.environ.get('PORT','8000'),'--workers','1','--threads','8','--timeout','60','--keep-alive','5','--error-logfile','-'])
