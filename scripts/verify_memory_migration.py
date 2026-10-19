"""Read-only backup comparison; never print account data or rewrite a database."""
import argparse
import sqlite3
import tempfile
from pathlib import Path
from zipfile import ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--database', default='backend/db.sqlite3')
    args = parser.parse_args()
    with ZipFile(args.backup) as archive, tempfile.TemporaryDirectory(dir=Path(args.backup).resolve().parent) as temp:
        assert archive.testzip() is None, 'backup_integrity_failed'
        snapshot = Path(temp) / 'snapshot.sqlite3'
        snapshot.write_bytes(archive.read('db.sqlite3'))
        old = sqlite3.connect(snapshot)
        live = sqlite3.connect('file:' + Path(args.database).resolve().as_posix() + '?mode=ro', uri=True)
        try:
            checks = {}
            for table in ('auth_user', 'web_friend', 'web_message', 'web_character', 'web_userprofile'):
                columns = [row[1] for row in old.execute('PRAGMA table_info(' + table + ')')]
                query = 'SELECT ' + ','.join(columns) + ' FROM ' + table + ' ORDER BY id'
                checks[table] = old.execute(query).fetchall() == live.execute(query).fetchall()
            assert all(checks.values()), 'original_records_changed_since_backup'
            print('original_rows_preserved:', checks)
            print('new_memory_rows:', live.execute('SELECT COUNT(*) FROM web_memoryitem').fetchone()[0])
        finally:
            old.close()
            live.close()


if __name__ == '__main__':
    main()
