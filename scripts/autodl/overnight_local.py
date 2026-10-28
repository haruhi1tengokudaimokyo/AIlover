"""Persistent local uploader/downloader. Shutdown only after all artifact checks pass."""
from datetime import datetime, timezone
from pathlib import Path
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import shutil
import subprocess
import time
import traceback
from zipfile import ZipFile

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / '训练成果' / 'AutoDL_四角色'
REMOTE = '/root/autodl-tmp/ailover'
CONNECTION_FILE = REPO / 'runtime/cloud-connection.json'
CONNECTION = json.loads(CONNECTION_FILE.read_text(encoding='utf-8-sig')) if CONNECTION_FILE.exists() else {}
HOST = os.getenv('AILOVER_SSH_HOST') or CONNECTION.get('host', 'localhost')
PORT = str(os.getenv('AILOVER_SSH_PORT') or CONNECTION.get('port', 22))
KEY = Path(os.getenv('AILOVER_SSH_KEY') or CONNECTION.get('key', str(Path.home() / '.ssh/id_ed25519')))
OPENSSH = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/OpenSSH'
SSH = [str(OPENSSH / 'ssh.exe'), '-n', '-T', '-i', str(KEY), '-p', PORT, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20',
       '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2', HOST]
SCP = [str(OPENSSH / 'scp.exe'), '-i', str(KEY), '-P', PORT, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20',
       '-o', 'ServerAliveInterval=30']


def log(stage, **values):
    data = {'updated_utc': datetime.now(timezone.utc).isoformat(), 'stage': stage, **values}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / '本地进度.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False), flush=True)


def run(args, timeout=3600):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:] or result.stdout[-3000:])
    return result.stdout


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def live_file_size(path):
    """Directory attributes can stay stale while Windows SCP holds a writer."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
    kernel.GetFileSizeEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80, 7, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        return None if path.exists() else 0
    try:
        length = ctypes.c_longlong()
        return length.value if kernel.GetFileSizeEx(handle, ctypes.byref(length)) else None
    finally:
        kernel.CloseHandle(handle)


def transfer_result(remote, partial, expected_size):
    # Legacy SCP avoids observed Windows SFTP stalls on the shared 17GB archive.
    command = SCP + ['-O', HOST + ':' + remote, str(partial)]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    started = last_growth = time.monotonic()
    previous = -1
    while True:
        try:
            stdout, stderr = process.communicate(timeout=10)
            if process.returncode:
                raise RuntimeError(stderr.decode('utf-8', errors='replace')[-3000:])
            return
        except subprocess.TimeoutExpired:
            size = live_file_size(partial)
            if size is not None and size > previous:
                last_growth, previous = time.monotonic(), size
            log('downloading_result', file=partial.name, downloaded_bytes=size, expected_bytes=expected_size)
            if (size is not None and time.monotonic() - last_growth > 180) or time.monotonic() - started > 14400:
                process.kill()
                process.communicate()
                raise TimeoutError('Transfer stopped making progress; retry without shutdown')


def download(entry):
    remote = entry['archive']
    if not remote.startswith(REMOTE + '/outputs/') or not remote.endswith('.zip') or any(c in remote for c in "'\r\n "):
        raise ValueError('Unexpected remote output path')
    dest = OUT / Path(remote).name
    if not dest.exists() or dest.stat().st_size != entry['bytes'] or sha(dest) != entry['sha256']:
        if shutil.disk_usage(OUT).free < entry['bytes'] + 2 * 1024**3:
            raise RuntimeError('Insufficient local space; refusing to shut down')
        partial = dest.with_suffix('.zip.part')
        log('downloading_result', file=dest.name, bytes=entry['bytes'])
        transfer_result(remote, partial, entry['bytes'])
        if partial.stat().st_size != entry['bytes'] or sha(partial) != entry['sha256']:
            raise ValueError('Downloaded model SHA256 mismatch')
        partial.replace(dest)
    with ZipFile(dest) as archive:
        if archive.testzip():
            raise ValueError('Local result ZIP CRC failure')
    return {**entry, 'local_path': str(dest), 'local_sha256': entry['sha256'], 'zip_verified': True}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Keep the machine awake for transfers; the screen may turn off normally.
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    manifest = json.loads((REPO / '训练材料/08_AutoDL上手指南/上传清单_SHA256.json').read_text(encoding='utf-8-sig'))['archives']
    for name, entry in manifest.items():
        if not name.startswith(('AIlover_Hika_', 'AIlover_Ayame_')):
            continue
        local = REPO / '训练材料' / entry['local_path']
        if local.stat().st_size != entry['bytes'] or sha(local) != entry['sha256']:
            raise ValueError('Source package failed integrity check: ' + name)
        existing = run(SSH + [f"if test -f /root/{name}; then sha256sum /root/{name}; fi"])
        if entry['sha256'] not in existing:
            log('uploading_remaining_character', file=name, bytes=entry['bytes'])
            run(SCP + [str(local), HOST + ':/root/' + name])
    log('verifying_remaining_packages')
    run(SSH + [f'/root/miniconda3/bin/python -u {REMOTE}/code/prepare_data.py --roles hika ayame'], timeout=1800)
    checked = {}
    while True:
        try:
            raw = run(SSH + [f'cat {REMOTE}/reports/overnight-artifacts.json'], timeout=45)
            cloud = json.loads(raw)
            for entry in cloud.get('artifacts', []):
                if entry['archive'] not in checked:
                    checked[entry['archive']] = download(entry)
                    (OUT / '已校验成果.json').write_text(json.dumps(list(checked.values()), ensure_ascii=False, indent=2), encoding='utf-8')
            if cloud.get('status') == 'all_complete':
                required = {(r, kind) for r in ('mugi', 'hotaru', 'hika', 'ayame') for kind in ('text', 'voice')}
                actual = {(e.get('role'), e.get('kind')) for e in checked.values()}
                if not required <= actual or not any(e.get('kind') == 'shared_base' for e in checked.values()):
                    raise ValueError('Incomplete four-character models or shared inference dependencies')
                # Recheck final on-disk bytes immediately before authorizing shutdown.
                for e in checked.values():
                    p = Path(e['local_path'])
                    if p.stat().st_size != e['bytes'] or sha(p) != e['sha256']:
                        raise ValueError('Final local persistence check failed')
                receipt = {'status': 'all_verified_on_local_disk', 'artifacts': list(checked.values()),
                           'manifest_sha256': hashlib.sha256(raw.encode()).hexdigest()}
                receipt_path = OUT / '完整回传确认.json'
                receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
                run(SCP + [str(receipt_path), f'{HOST}:{REMOTE}/reports/local-backup-receipt.json'])
                log('all_models_saved_and_verified_requesting_shutdown', directory=str(OUT))
                try:
                    run(SSH + [f'/root/miniconda3/bin/python {REMOTE}/code/finalize_shutdown.py'], timeout=45)
                except Exception as exc:
                    # Shutdown can sever SSH before a successful exit is returned.
                    log('shutdown_requested_verify_instance_status', detail=str(exc))
                return
            log('waiting_for_training', remote_status=cloud.get('status'), local_artifacts=len(checked))
        except Exception as exc:
            log('retrying_without_shutdown', detail=str(exc))
        time.sleep(60)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log('failed_no_shutdown', traceback=traceback.format_exc())
        raise
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
