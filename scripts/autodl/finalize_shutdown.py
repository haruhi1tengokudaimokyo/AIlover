"""Only run AutoDL shutdown after every expected result is verified locally."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path('/root/autodl-tmp/ailover')


def validate(manifest_text, receipt):
    manifest = json.loads(manifest_text)
    assert manifest['status'] == 'all_complete', 'Training not complete'
    assert receipt['status'] == 'all_verified_on_local_disk', 'No verified local backup'
    assert receipt['manifest_sha256'] == hashlib.sha256(manifest_text.encode()).hexdigest(), 'Receipt references different manifest'
    required = {(r, k) for r in ('mugi', 'hotaru', 'hika', 'ayame') for k in ('text', 'voice')}
    assert required <= {(e.get('role'), e.get('kind')) for e in manifest['artifacts']}, 'Missing role model'
    assert any(e.get('kind') == 'shared_base' for e in manifest['artifacts']), 'Missing base dependencies'
    local = {e['archive']: e for e in receipt['artifacts']}
    for entry in manifest['artifacts']:
        item = local[entry['archive']]
        assert item['sha256'] == item['local_sha256'] == entry['sha256']
        assert item['bytes'] == entry['bytes'] and item['zip_verified'] is True
    return manifest


def main():
    manifest = validate((ROOT / 'reports/overnight-artifacts.json').read_text(),
                        json.loads((ROOT / 'reports/local-backup-receipt.json').read_text()))
    marker = {'run_id': manifest['run_id'], 'requested_utc': datetime.now(timezone.utc).isoformat(),
              'reason': 'All four text/voice results and shared dependencies verified on local disk'}
    (ROOT / 'reports/shutdown-requested.json').write_text(json.dumps(marker, indent=2))
    print('LOCAL_BACKUP_VERIFIED_REQUESTING_AUTODL_SHUTDOWN', flush=True)
    # AutoDL ships a shell script without a shebang; execve directly returns
    # ENOEXEC, whereas the documented interactive shell command works.
    subprocess.run(['/bin/bash', '/usr/bin/shutdown'], check=True)


if __name__ == '__main__':
    main()
