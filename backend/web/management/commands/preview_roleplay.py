"""Preview safe metadata for the actual context path, with no API invocation."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from langchain_core.messages import HumanMessage
from web.views.friend.message.chat.chat import add_system_prompt


class Command(BaseCommand):
    help = '离线检查实际角色上下文注入，只输出 ID/预算/计数，不输出原作或 prompt'

    def add_arguments(self, parser):
        parser.add_argument('--slug', choices=['hika','ayame'], default='hika')
        parser.add_argument('--message', required=True)
        parser.add_argument('--identity-mode', choices=['real_user','protagonist'], default='real_user')
        parser.add_argument('--output')

    def handle(self, *args, **options):
        if not 1 <= len(options['message']) <= 2000:
            raise CommandError('消息长度需为1到2000字')
        card = json.loads((Path(settings.BASE_DIR) / 'seed_cards' / f'{options["slug"]}.json').read_text(encoding='utf-8'))
        friend = SimpleNamespace(character=SimpleNamespace(name=card['name'],profile=card['profile'],slug=card['slug']),
                                 memory='',memory_enabled=False)
        with patch.dict(os.environ, {'ROLEPLAY_RAG_MODE':'story','STORY_RETRIEVAL_STRATEGY':'sparse',
                                     'STORY_DENSE_ENABLED':'false','ROLEPLAY_IDENTITY_MODE':options['identity_mode']}):
            result = add_system_prompt({'messages':[HumanMessage(options['message'])]},friend,options['message'])
        report = {'slug':options['slug'],'api_calls':0,'messages':len(result['messages']),
                  'trace':result['trace'],'notice':'只有实际注入契约，不评价真实模型效果；正文不写入报告。'}
        if options['output']:
            target = Path(options['output'])
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('x',encoding='utf-8') as handle:
                json.dump(report,handle,ensure_ascii=False,indent=2)
        self.stdout.write(json.dumps(report,ensure_ascii=False,indent=2))
