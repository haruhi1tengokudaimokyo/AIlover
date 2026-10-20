"""Run an isolated offline UI preview; never writes to the user's real database.

Usage: .venv/Scripts/python.exe scripts/preview_redesign.py
Login: redesign-preview / preview-only-2026 (only in the temporary copy).
"""
import argparse
import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fixture-stream', action='store_true', help='Use a deterministic local SSE fixture; never call a model service')
options = parser.parse_args()
temporary = Path(tempfile.mkdtemp(prefix='ailover-redesign-'))
source = sqlite3.connect(f'file:{(root / "backend/db.sqlite3").as_posix()}?mode=ro', uri=True)
target = sqlite3.connect(temporary / 'db.sqlite3')
source.backup(target)
target.close()
source.close()
os.environ.update(AI_LOVER_DATA_DIR=str(temporary), AI_LOVER_MEDIA_ROOT=str(root / 'backend/media'),
                  API_KEY='offline-fixture-only' if options.fixture_stream else '', TTS_ENABLED='false',
                  ROLEPLAY_RAG_MODE='off', DJANGO_SETTINGS_MODULE='backend.settings')
sys.path.insert(0, str(root / 'backend'))
import django
django.setup()
from django.contrib.auth.models import User
from web.models.user import UserProfile
from django.core.management import call_command
user, _ = User.objects.get_or_create(username='redesign-preview')
user.set_password('preview-only-2026')
user.save()
UserProfile.objects.get_or_create(user=user)
if options.fixture_stream:
    from langchain_core.messages import AIMessageChunk
    from web.views.friend.message.chat.graph import ChatGraph

    class PreviewModel:
        async def astream(self, *args, **kwargs):
            for char in '今天辛苦啦。把那些忙碌先留在门外吧，我们慢慢聊。我会在这里，听你说。':
                await asyncio.sleep(0.2)
                yield AIMessageChunk(content=char), {}

    ChatGraph.create_app = staticmethod(PreviewModel)
    print('FIXTURE STREAM: local deterministic tokens only, not a real model or TTS.', flush=True)
print('Offline preview: http://127.0.0.1:8001 | isolated database:', temporary, flush=True)
call_command('runserver', '127.0.0.1:8001', use_reloader=False)
