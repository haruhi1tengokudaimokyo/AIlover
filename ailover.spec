# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置：把 Django 后端 + 已构建的前端打成一个 AIlover.exe

用法（在仓库根目录）：
    .venv/Scripts/python -m PyInstaller ailover.spec --clean --noconfirm
产物：dist/AIlover.exe
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

datas = [
    # Django 项目代码（含模板、静态前端）
    ('backend/backend', 'backend/backend'),
    ('backend/web', 'backend/web'),
    ('backend/manage.py', 'backend'),
    ('backend/static', 'backend/static'),
    # 《王様恋愛》角色卡与种子素材（含参考音频）
    ('backend/seed_cards', 'backend/seed_cards'),
    ('backend/seed_assets', 'backend/seed_assets'),
    ('backend/evaluation', 'backend/evaluation'),
]

hiddenimports = [
    'web', 'web.views', 'web.models', 'web.documents',
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'corsheaders',
]

# 这些包有数据文件 / 动态导入，整体收集
for pkg in ['lancedb', 'langgraph', 'langchain_openai', 'langchain_core',
            'rest_framework', 'rest_framework_simplejwt', 'dotenv',
            'whitenoise', 'waitress', 'corsheaders', 'PIL',
            'django.contrib.admin', 'django.contrib.auth',
            'django.contrib.contenttypes', 'django.contrib.sessions',
            'django.contrib.messages', 'django.contrib.staticfiles']:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        hiddenimports += h
    except Exception:
        pass

# langchain_community 的向量库是在函数内延迟导入的，单独点名（不整包收集，太慢）
hiddenimports += [
    'langchain_community.vectorstores',
    'langchain_community.vectorstores.lancedb',
    'langchain_community.embeddings',
]

# Django 各 app 的模板/静态文件
datas += collect_data_files('django.contrib.admin')
datas += collect_data_files('django.contrib.auth')

a = Analysis(
    ['launcher.py'],
    pathex=['.', 'backend'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'tensorflow', 'matplotlib', 'tkinter', 'PyQt5', 'PyQt6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AIlover',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,   # 保留控制台窗口便于查看日志；确认无误后可改为 False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AIlover',
)
