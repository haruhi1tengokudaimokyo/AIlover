import asyncio
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, Mock
from django.test import SimpleTestCase
from django.conf import settings
from web.character_runtime import character_route, voice_for_character
from web.views.friend.message.chat.voice import GPTSoVITSProvider, SentenceQueue


class TrainedRoutingTests(SimpleTestCase):
    def setUp(self):
        temporary_root = Path(settings.BASE_DIR).parent / 'runtime/test-tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'manifest.json'
        self.path.write_text(json.dumps({'characters': {r: {'model': 'ailover-' + r,
            'api_base': 'http://127.0.0.1:8001/v1', 'tts_url': 'http://127.0.0.1:9891',
            'reference_audio': '/references/' + r + '.wav', 'reference_text': 'こんにちは。'}
            for r in ('hika', 'ayame', 'mugi', 'hotaru')}}))
        self.env = patch.dict(os.environ, CHARACTER_MODELS_ENABLED='true', CHARACTER_MODELS_MANIFEST=str(self.path))
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_each_role_is_isolated_and_unknown_role_not_routed(self):
        for role in ('hika', 'ayame', 'mugi', 'hotaru'):
            self.assertEqual(character_route(role)['model'], 'ailover-' + role)
            self.assertEqual(voice_for_character(SimpleNamespace(slug=role, voice='generic')), 'trained:' + role)
        self.assertIsNone(character_route('user-created'))

    def test_disabled_mode_preserves_existing_voice(self):
        with patch.dict(os.environ, CHARACTER_MODELS_ENABLED='false'):
            self.assertIsNone(character_route('mugi'))
            self.assertEqual(voice_for_character(SimpleNamespace(slug='mugi', voice='generic')), 'generic')

    def test_text_only_remote_route_does_not_require_or_call_gpu_voice(self):
        data = json.loads(self.path.read_text())
        for route in data['characters'].values():
            route.pop('tts_url')
            route['tts_provider'] = 'disabled'
        self.path.write_text(json.dumps(data))
        for role in ('hika', 'ayame', 'mugi', 'hotaru'):
            self.assertEqual(character_route(role)['model'], 'ailover-' + role)
            self.assertEqual(voice_for_character(SimpleNamespace(slug=role, voice='generic')), '')

    def test_invalid_manifest_does_not_silently_use_another_role(self):
        self.path.write_text('{}')
        with self.assertRaises(KeyError):
            character_route('mugi')

    def test_graph_uses_role_adapter_without_binding_untrained_tools(self):
        from web.views.friend.message.chat.graph import ChatGraph
        with patch('web.views.friend.message.chat.graph.ChatOpenAI') as model:
            ChatGraph.create_app('hotaru')
            self.assertEqual(model.call_args.kwargs['model'], 'ailover-hotaru')
            self.assertEqual(model.call_args.kwargs['openai_api_base'], 'http://127.0.0.1:8001/v1')
            model.return_value.bind_tools.assert_not_called()

    def test_japanese_reference_chinese_target_and_real_mp3_transport(self):
        async def run():
            metrics = {'sentence_count': 0, 'errors': [], 'queue_wait_count': 0,
                       'queue_wait_total_ms': 0, 'queue_wait_max_ms': 0}
            queue = SentenceQueue(metrics)
            queue.offer('今天很高兴见到你。')
            queue.finish()
            response = Mock(content=b'RIFF' + b'valid-wave')
            client = AsyncMock()
            client.post.return_value = response
            process = Mock(returncode=0, communicate=AsyncMock(return_value=(b'ID3actual-mp3', b'')))
            output = []
            with patch('httpx.AsyncClient') as factory, patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)):
                factory.return_value.__aenter__.return_value = client
                await GPTSoVITSProvider().stream(queue, output.append, 'trained:mugi')
            payload = client.post.call_args.kwargs['json']
            self.assertEqual((payload['text_lang'], payload['prompt_lang']), ('zh', 'ja'))
            self.assertEqual(payload['ref_audio_path'], '/references/mugi.wav')
            self.assertEqual(len(output), 1)
            self.assertTrue(queue.eof_consumed)
        asyncio.run(run())
