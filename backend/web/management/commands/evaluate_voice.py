"""Transport/latency ablation with explicit synthetic models, never paid APIs."""
import asyncio
import base64
import json
import os
import threading
import time
from pathlib import Path
from queue import Queue
from unittest.mock import patch
from django.core.management.base import BaseCommand
from langchain_core.messages import AIMessageChunk
from web.views.friend.message.chat.chat import MessageChatView
from web.views.friend.message.chat.generation import Generation


class MockModel:
    text = '这是合成语音测试。后续文字继续生成。'
    async def astream(self, *args, **kwargs):
        for char in self.text:
            await asyncio.sleep(.002)
            yield AIMessageChunk(content=char), {}


class MockVoice:
    async def stream(self, texts, emit, voice):
        while True:
            item = await texts.get()
            if item is None:
                return
            wait = (time.monotonic() - item.queued_at) * 1000
            texts.metrics['queue_wait_count'] += 1
            texts.metrics['queue_wait_total_ms'] += wait
            texts.metrics['queue_wait_max_ms'] = max(texts.metrics['queue_wait_max_ms'], wait)
            await asyncio.sleep(.004)
            emit({'audio': base64.b64encode(b'mock-transport-not-real-audio').decode()})


class Command(BaseCommand):
    help = '离线 Mock 语音消融；不是云端性能或真实音频质量评测，不写聊天数据库'

    def add_arguments(self, parser):
        parser.add_argument('--output')

    def handle(self, *args, **options):
        async def evaluate():
            report = {'synthetic': True, 'provider': 'deterministic_mock_delays', 'real_audio': False, 'api_calls': 0, 'runs': []}
            for segmented in ('false', 'true'):
                view, generation, queue = MessageChatView(), Generation(None, ''), Queue()
                view.tts_provider = MockVoice()
                with patch.dict(os.environ, {'TTS_SENTENCE_BUFFER': segmented, 'TTS_ENABLED': 'true'}):
                    await view.run_tasks(MockModel(), {'messages': []}, queue, 'mock', True, threading.Event(), generation)
                generation.finish(); generation.close_stream()
                joined = ''.join(p.get('content', '') for p in queue.queue)
                assert joined == MockModel.text
                report['runs'].append({'segmented': segmented == 'true', 'text_complete': True, **generation.metrics})
            return report
        report = asyncio.run(evaluate())
        if options['output']:
            target = Path(options['output'])
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8') as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
