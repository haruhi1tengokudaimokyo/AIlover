# -*- coding: utf-8 -*-
"""
AIlover 桌面版启动器（exe 入口）。

双击后：
1. 初始化数据目录（exe 旁边的 data/：数据库 + 媒体文件）
2. 自动执行数据库迁移
3. 启动内嵌 HTTP 服务（waitress）
4. 弹出原生桌面窗口（pywebview）；失败则退回系统浏览器
"""
import os
import sys
import socket
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = 'AIlover'
DEFAULT_PORT = 8000


def is_frozen():
    return getattr(sys, 'frozen', False)


def base_dir() -> Path:
    """代码根目录：开发时是 backend/，打包后是 PyInstaller 解包目录中的 backend/"""
    if is_frozen():
        return Path(sys._MEIPASS) / 'backend'
    return Path(__file__).resolve().parent / 'backend'


def data_dir() -> Path:
    """数据目录：打包后是 exe 旁边的 data/，开发时是 backend/"""
    if is_frozen():
        d = Path(sys.executable).resolve().parent / 'data'
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path(__file__).resolve().parent / 'backend'


def setup_env():
    backend = base_dir()
    os.chdir(backend)  # Django 相对路径（如 .env、lancedb）都基于这里
    os.environ.setdefault('AI_LOVER_DATA_DIR', str(data_dir()))
    os.environ.setdefault('DEBUG', 'False')
    sys.path.insert(0, str(backend))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
    # 依次尝试加载密钥配置：exe 旁边 data/.env > 代码目录 .env
    try:
        from dotenv import load_dotenv
        load_dotenv(data_dir() / '.env')
        load_dotenv(backend / '.env')
    except ImportError:
        pass


def find_free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 20)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError('找不到可用端口')


def run_server(port: int):
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', interactive=False, verbosity=0)

    from django.core.wsgi import get_wsgi_application
    from waitress import serve
    app = get_wsgi_application()
    serve(app, host='127.0.0.1', port=port, threads=8, _quiet=True)


def wait_ready(port: int, timeout: float = 30.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def run_seed_murasame(username: str | None):
    """命令行种子模式：AIlover.exe --seed-murasame [用户名]"""
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', interactive=False, verbosity=0)
    call_command('seed_murasame', username=username)
    print('\n丛雨角色已就绪，启动程序后在「创建角色/添加好友」里就能找到她。')


def run_seed_ousama(username: str | None):
    """命令行种子模式：AIlover.exe --seed-ousama [用户名]（绯华与菖蒲）"""
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', interactive=False, verbosity=0)
    call_command('seed_ousama', username=username)
    print('\n绯华、菖蒲角色已就绪，启动程序后在「添加好友」里就能找到她们。')


def main():
    setup_env()

    if '--seed-murasame' in sys.argv:
        idx = sys.argv.index('--seed-murasame')
        username = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        run_seed_murasame(username)
        return

    if '--seed-ousama' in sys.argv:
        idx = sys.argv.index('--seed-ousama')
        username = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        run_seed_ousama(username)
        return

    port = find_free_port(DEFAULT_PORT)
    url = f'http://127.0.0.1:{port}/'

    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()

    if not wait_ready(port):
        print('服务启动超时，请查看日志。')
        sys.exit(1)

    if '--no-window' in sys.argv:
        # 无窗口模式（调试/测试用）：只起服务，保持进程存活
        print(f'服务已启动: {url}（--no-window 模式，Ctrl+C 退出）')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    try:
        import webview
        webview.create_window(APP_NAME, url, width=1280, height=800, min_size=(960, 640))
        webview.start()
    except Exception as e:
        print(f'桌面窗口不可用（{e}），改用系统浏览器打开。')
        webbrowser.open(url)
        # 浏览器模式下保持进程存活
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
