"""Read-only uploaded ZIP verification and exact package extraction on AutoDL."""
import hashlib
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path('/root/autodl-tmp/ailover')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--roles', nargs='+', choices=('mugi', 'hotaru', 'hika', 'ayame'), default=['mugi', 'hotaru'])
    args = parser.parse_args()
    expected = json.loads((ROOT / 'code/upload_manifest.json').read_text())['archives']
    target_report = ROOT / 'reports/data-ready.json'
    result = json.loads(target_report.read_text()) if target_report.exists() else {}
    for role in args.roles:
        label = role.capitalize()
        result[role] = {}
        for kind, suffix in [('text', 'Text_V3'), ('voice', 'TTS_Preparation_V1')]:
            name = f'AIlover_{label}_{suffix}.zip'
            source = Path('/root') / name
            target = ROOT / 'incoming' / name
            entry = expected[name]
            for p in (source,):
                if p.stat().st_size != entry['bytes'] or sha(p) != entry['sha256']:
                    raise ValueError('Uploaded file incomplete: ' + name)
            if not target.exists():
                shutil.copyfile(source, target)
            if sha(target) != entry['sha256']:
                raise ValueError('Data-disk copy differs: ' + name)
            package = ROOT / 'packages' / target.stem
            if not package.exists():
                with ZipFile(target) as z:
                    names = z.namelist()
                    if len(set(names)) != len(names):
                        raise ValueError('Duplicate ZIP member')
                    for n in names:
                        p = PurePosixPath(n)
                        if p.is_absolute() or '..' in p.parts or ':' in n or '\\' in n or p.parts[0] != target.stem:
                            raise ValueError('Unsafe ZIP entry')
                    if z.testzip():
                        raise ValueError('ZIP CRC failure')
                    (ROOT / 'packages').mkdir(exist_ok=True)
                    z.extractall(ROOT / 'packages')
            subprocess.run([sys.executable, '-B', str(package / 'tools/verify.py'), 'verify', '--root', str(package)], check=True)
            result[role][kind] = str(package)
            print('PACKAGE_VERIFIED', name, flush=True)
    temp = target_report.with_suffix('.tmp')
    temp.write_text(json.dumps(result, indent=2))
    temp.replace(target_report)


if __name__ == '__main__':
    main()
