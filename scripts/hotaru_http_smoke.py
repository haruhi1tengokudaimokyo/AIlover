"""Real local HTTP checks on an isolated copy of the installed Hotaru database.

Only login, role search, friend loading, SPA and original image assets are used.
No LLM, TTS, ASR, training, prompt generation or user-chat mutation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from wsgiref.simple_server import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    source = ROOT / 'backend/db.sqlite3'
    before = sha(source)
    data = ROOT / 'backend/evaluations' / ('hotaru-http-' + secrets.token_hex(6))
    data.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(source) as original, sqlite3.connect(data / 'db.sqlite3') as copy:
        original.backup(copy)
    os.environ.update(AI_LOVER_DATA_DIR=str(data), DJANGO_SETTINGS_MODULE='backend.settings',
                      API_KEY='', TTS_ENABLED='false', STORY_DENSE_ENABLED='false', DEBUG='True',
                      STORY_DATA_DIR=str(ROOT / 'backend/story_data'))
    sys.path.insert(0, str(ROOT / 'backend'))
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth.models import User
    from django.core.wsgi import get_wsgi_application
    from django.db import connections
    from web.models.character import Character
    from web.models.user import UserProfile
    settings.MEDIA_ROOT = ROOT / 'backend/media'
    if Path(settings.DATABASES['default']['NAME']).resolve() != (data / 'db.sqlite3').resolve():
        raise ValueError('Refusing to write an unisolated database')
    character = Character.objects.get(slug='hotaru')
    username = 'hotaru-http-' + secrets.token_hex(5)
    password = secrets.token_urlsafe(24)
    user = User.objects.create_user(username=username, password=password)
    UserProfile.objects.create(user=user)

    class SilentHandler(WSGIRequestHandler):
        def log_message(self, format, *args):
            pass

    application = get_wsgi_application()

    def guarded(environ, start_response):
        if environ.get('PATH_INFO') in ('/api/friend/message/chat/', '/api/friend/message/asr/asr/'):
            start_response('403 Forbidden', [('Content-Type', 'text/plain')])
            return [b'External inference disabled for isolated role/asset HTTP checks.']
        return application(environ, start_response)

    server = make_server('127.0.0.1', 0, guarded, handler_class=SilentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    token = None

    def request(path, body=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        encoded = json.dumps(body).encode() if body is not None else None
        return urlopen(Request(base + path, encoded, headers), timeout=20)

    def api(path, body=None):
        with request(path, body) as response:
            return json.load(response)

    try:
        login = api('/api/user/account/login/', {'username': username, 'password': password})
        assert login['result'] == 'success'
        token = login['access']
        search = api('/api/homepage/index/?' + urlencode({'search_query': '水无月萤'}))
        match = next(row for row in search['characters'] if row['id'] == character.pk)
        assert match['slug'] == 'hotaru' and match['greeting'] and len(match['quick_replies']) == 3
        created = api('/api/friend/get_or_create/', {'character_id': character.pk})
        friend_id = created['friend']['id']
        loaded = api('/api/friend/get_single/?' + urlencode({'friend_id': friend_id}))
        assert loaded['friend']['character']['slug'] == 'hotaru'
        expected = (match['photo'], match['background_image'], match['assets']['portrait_url'])
        statuses = {}
        for path in ('/', f'/chat/{friend_id}', *expected):
            assert path
            with request(path) as response:
                data_bytes = response.read()
                assert response.status == 200 and data_bytes
                if path.endswith('.webp'):
                    assert data_bytes[:4] == b'RIFF' and data_bytes[8:12] == b'WEBP'
                statuses[path] = response.status
        assert sha(source) == before, 'Real application database changed during isolated HTTP checks'
        report = dict(slug='hotaru', transport='actual local WSGI HTTP',
                      isolated_database=str(data / 'db.sqlite3'), original_database_unchanged=True,
                      search=True, friend_create_and_load=True, greeting_and_topics=True,
                      status_by_path=statuses, external_api_calls=0, training_or_inference_run=False,
                      browser_clicks_verified=False, real_user_chat_modified=False)
        target = ROOT / 'docs/evaluation/hotaru-http-smoke.json'
        with target.open('x', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        connections.close_all()


if __name__ == '__main__':
    main()
