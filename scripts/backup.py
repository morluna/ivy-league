"""Consistent online SQLite backup. Run manually or from the host's scheduler."""
import argparse
import sqlite3
from pathlib import Path

def backup(source, destination):
    if Path(source).resolve() == Path(destination).resolve():
        raise ValueError('Choose a different backup path.')
    if Path(destination).exists():
        raise ValueError('Backup destination already exists; choose a new filename.')
    with sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro',uri=True) as src:
        with sqlite3.connect(destination) as dest:
            src.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup integrity check failed.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('destination')
    args = parser.parse_args()
    backup(args.source,args.destination)
    print('Backup complete; store a copy outside the hosting disk.')
