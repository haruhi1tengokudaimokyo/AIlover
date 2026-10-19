"""Read-only verification of the review archive; does not execute bundled code."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    args = parser.parse_args()
    path = Path(args.archive)
    with ZipFile(path) as archive:
        assert archive.testzip() is None, 'zip_integrity_failed'
        names = archive.namelist()
        assert len(names) == len(set(names)), 'duplicate_entries'
        for name in names:
            relative = PurePosixPath(name)
            assert not relative.is_absolute() and '..' not in relative.parts and '\\' not in name and ':' not in name, 'unsafe_path'
        manifest = json.loads(archive.read('AIlover-review/FILE_MANIFEST.json'))
        expected = {'AIlover-review/' + item['path'] for item in manifest['files']}
        expected.update({'AIlover-review/00_READ_FIRST.md', 'AIlover-review/PROJECT_REVIEW.txt', 'AIlover-review/FILE_MANIFEST.json'})
        assert set(names) == expected, 'unexpected_or_missing_file'
        compiled = 0
        for item in manifest['files']:
            data = archive.read('AIlover-review/' + item['path'])
            assert len(data) == item['bytes'], 'size_mismatch'
            assert hashlib.sha256(data).hexdigest() == item['sha256'], 'hash_mismatch'
            if item['path'].endswith(('.py', '.spec')):
                compile(data, item['path'], 'exec')
                compiled += 1
        if not manifest['private_corpus_included']:
            assert not any('character_lines' in PurePosixPath(name).parts or 'seed_assets' in PurePosixPath(name).parts for name in names), 'private_corpus'
            assert 'AIlover-review/PROJECT_CORPUS_AUDIT.json' not in names, 'quoted_corpus_audit'
        assert not any(PurePosixPath(name).name == '.env' or name.endswith(('.sqlite3', '.db', '.log', '.exe')) for name in names), 'private_runtime'
    print(json.dumps({'files': len(manifest['files']), 'python_sources_compiled': compiled,
                      'integrity': 'passed', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
