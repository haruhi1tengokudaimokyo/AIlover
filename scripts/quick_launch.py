"""Small Windows EXE entry for this checkout; uses its venv and existing data."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request


def notice(message):
    ctypes.windll.user32.MessageBoxW(None, message, 'AIlover', 0)


def main():
    root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    verify = '--verify' in sys.argv
    python = root / '.venv/Scripts/pythonw.exe'
    entry = root / 'launcher.py'
    if not python.is_file() or not entry.is_file():
        if not verify:
            notice('请将启动 EXE 放在 AIlover 项目根目录，和 launcher.py、.venv 文件夹放在一起。')
        return 1
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    identity = hashlib.sha256(str(root).lower().encode()).hexdigest()[:24]
    if verify:
        identity += '-verify'
    handle = kernel.CreateMutexW(None, True, 'Local\\AIloverQuickLaunch-' + identity)
    if not handle:
        return 1
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        if not verify:
            notice('AIlover 已经在运行，请查看任务栏中的 AIlover 窗口。')
        return 0
    logs = root / 'runtime/desktop'
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / ('startup-' + time.strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid()) + '.log')
    (logs / 'latest-log.txt').write_text(str(log), encoding='utf-8')
    child = None
    try:
        args = [str(python), '-u', str(entry)] + (['--no-window'] if verify else [])
        with log.open('wb') as output:
            child = subprocess.Popen(args, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                     env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            if verify:
                deadline = time.monotonic() + 65
                success = False
                url = None
                lazy_assets = set()
                while time.monotonic() < deadline and child.poll() is None:
                    content = log.read_text(encoding='utf-8', errors='replace')
                    match = re.search(r'http://127\.0\.0\.1:\d+/', content)
                    if match:
                        url = match.group()
                        try:
                            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                            with opener.open(url, timeout=3) as response:
                                page = response.read().decode('utf-8')
                                success = response.status == 200 and 'AIlover' in page
                            assets = re.findall(r'(?:src|href)="(/static/frontend/[^\"]+)"', page)
                            entry_source = ''
                            success = success and len(assets) >= 2
                            for asset in assets:
                                with opener.open(url.rstrip('/') + asset, timeout=5) as response:
                                    body = response.read()
                                    if asset.endswith('.js'):
                                        success = success and 'javascript' in response.headers.get('Content-Type', '')
                                        entry_source = body.decode('utf-8')
                                    if asset.endswith('.css'):
                                        success = success and 'text/css' in response.headers.get('Content-Type', '')
                            # A 200 HTML shell alone missed the original blank-screen bug.
                            success = success and bool(re.search(r'return[\"\u0027]/static/frontend/[\"\u0027]\+', entry_source))
                            lazy_assets = set(re.findall(r'"(assets/[^\"]+\.(?:js|css))"', entry_source))
                            for asset in lazy_assets:
                                with opener.open(url + 'static/frontend/' + asset, timeout=5) as response:
                                    content_type = response.headers.get('Content-Type', '')
                                    success = success and (('text/css' if asset.endswith('.css') else 'javascript') in content_type)
                            if success:
                                break
                        except (OSError, ValueError):
                            pass
                    time.sleep(.3)
                (logs / 'startup-check.json').write_text(json.dumps({'success': success, 'url': url,
                    'log': str(log), 'mode': 'real_exe_frontend_assets_check',
                    'lazy_asset_count': len(lazy_assets) if url else 0}, indent=2), encoding='utf-8')
                return 0 if success else 1
            code = child.wait()
            if code:
                notice('AIlover 启动失败。日志位置：\n' + str(log))
            return code
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    try:
        code = main()
    except Exception:
        notice('启动器遇到错误，请查看项目 runtime/desktop 中的启动日志。')
        code = 1
    sys.exit(code)
