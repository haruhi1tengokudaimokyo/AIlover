"""Adopt the already-running final SCP without throwing away transferred bytes."""
import argparse
import ctypes
from ctypes import wintypes
import json
import time
from zipfile import ZipFile

import overnight_local as worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    args = parser.parse_args()
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    name = 'AIlover_Shared_Base_Models_quality-20261027T180433Z.zip'
    partial = worker.OUT / (name + '.part')
    handle = kernel.OpenProcess(0x100000, False, args.pid)
    if handle:
        try:
            while kernel.WaitForSingleObject(handle, 10000) == 258:
                worker.log('downloading_shared_base_existing_transfer', file=name,
                           downloaded_bytes=worker.live_file_size(partial), expected_bytes=17312519961,
                           note='active SCP preserved; Windows writer may hide live length')
        finally:
            kernel.CloseHandle(handle)
    expected_sha = 'b5499d05d14d52304199ce5bd29fe8b70705fb7a86a0913c8ebcf801f969043d'
    worker.log('verifying_shared_base_download', file=name)
    if partial.exists() and partial.stat().st_size == 17312519961 and worker.sha(partial) == expected_sha:
        with ZipFile(partial) as archive:
            if archive.testzip():
                raise ValueError('Shared base archive CRC mismatch')
        partial.replace(worker.OUT / name)
    # The normal worker independently rechecks the remote manifest and all files
    # before issuing a signed-by-state local receipt and the shutdown request.
    worker.main()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        worker.log('failed_no_shutdown', detail=str(exc))
        raise
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
