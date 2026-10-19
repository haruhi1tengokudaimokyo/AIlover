"""Explicit isolated UI fixture server. No real model, TTS, ASR or user DB.

Only a new directory beneath backend/evaluations is accepted; existing data is
never reset. This script is not imported by the application or desktop launcher.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--port', type=int, default=8007)
    args = parser.parse_args()
    data = Path(args.data_dir).resolve()
    if not data.is_relative_to(root / 'backend/evaluations') or data.exists():
        raise SystemExit('Use a NEW directory beneath backend/evaluations; existing data is never modified.')
    data.mkdir(parents=True)
    os.environ.update(AI_LOVER_DATA_DIR=str(data), API_KEY='OFFLINE_UI_FIXTURE_NOT_A_REAL_KEY',
                      MODEL='offline-ui-fixture', TTS_ENABLED='false', STORY_DENSE_ENABLED='false',
                      MEMORY_MODE='structured', DEBUG='True', ROLEPLAY_DEBUG_TRACE='true',
                      STORY_DATA_DIR=str(data / 'story_data'), DJANGO_SETTINGS_MODULE='backend.settings')
    sys.path.insert(0, str(root / 'backend'))
    import django
    django.setup()
    from django.core.management import call_command
    from django.contrib.auth.models import User
    from django.core.wsgi import get_wsgi_application
    from langchain_core.messages import AIMessageChunk
    from rest_framework.response import Response
    from web.models.user import UserProfile
    from web.models.character import Character
    from web.models.friend import Friend, Message
    from web.views.friend.message.memory.structured import enqueue, process_job
    from web.views.friend.message.chat.graph import ChatGraph
    from web.views.friend.message.asr.asr import ASRView
    from waitress import serve
    call_command('migrate', interactive=False, verbosity=0)
    user = User.objects.create_user(username='ui_fixture', password='OfflineUI_2026!')
    profile = UserProfile.objects.create(user=user)
    character = Character.objects.create(author=profile, name='离线核验角色', slug='synthetic',
        profile='仅用于软件界面核验，不代表原作人物或真实模型效果。', greeting='这是隔离的合成核验环境。')
    friend = Friend.objects.create(me=profile, character=character)
    source = Message.objects.create(friend=friend, user_message='叫我界面测试者', input='', output='合成来源消息。')
    process_job(enqueue(source).pk)
    corpus = data / 'story_data'; corpus.mkdir()
    rows = json.loads((root / 'backend/evaluation/conversation_evidence_synthetic.json').read_text(encoding='utf-8'))['records']
    for channel, name in (('lore','story_knowledge'),('style','dialogue_examples')):
        (corpus / f'{name}.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n'
            for row in rows if row['evidence_type']==channel),encoding='utf-8')

    class FixtureGraph:
        async def astream(self, *args, **kwargs):
            text = '这是离线界面核验的合成回复，不代表真实角色能力。文字分段用于验证停止、下一轮隔离与记忆来源显示。'
            for char in text:
                await asyncio.sleep(.08)
                yield AIMessageChunk(content=char), {}
    ChatGraph.create_app = staticmethod(lambda: FixtureGraph())
    ASRView.post = lambda self, request: Response({'result':'离线核验不调用 ASR 服务'},status=503)
    print(f'OFFLINE UI FIXTURE pid={os.getpid()} port={args.port}; database isolated; all external APIs disabled.',flush=True)
    application = get_wsgi_application()
    def marked_fixture(environ, start_response):
        def start(status, headers, exc_info=None):
            return start_response(status, headers + [('X-AIlover-Isolated-Fixture','true')], exc_info)
        return application(environ, start)
    serve(marked_fixture,host='127.0.0.1',port=args.port,threads=8)


if __name__ == '__main__':
    main()
