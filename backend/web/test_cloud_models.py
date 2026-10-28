import asyncio
import base64
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import time
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from django.conf import settings
from django.test import SimpleTestCase
from langchain_core.messages import HumanMessage
from web.cloud_models import DashScopeCustomChat, RunPodVoiceProvider
from web.views.friend.message.chat.voice import SentenceQueue


class CloudProviderTests(SimpleTestCase):
    def queue(self):
        q = SentenceQueue({'sentence_count': 0, 'errors': []})
        q.offer('你好。')
        q.finish()
        return q

    def execute_voice(self, mode):
        async def run():
            sent, calls, result = {}, [], []
            async def transport(request):
                calls.append(request.url.path)
                self.assertEqual(request.headers['Authorization'], 'Bearer fixture-key')
                if request.url.path.endswith('/run'):
                    sent.update(json.loads(request.content)['input'])
                    return httpx.Response(200, json={'id': 'test-job'})
                if '/cancel/' in request.url.path:
                    return httpx.Response(200, json={'status': 'CANCELLED'})
                if mode in ('timeout', 'cancel'):
                    await asyncio.sleep(1)
                if mode == 'transient' and sum('/status/' in c for c in calls) == 1:
                    return httpx.Response(503)
                output = {'role': 'hotaru' if mode == 'wrong-role' else 'mugi', 'request_id': sent['request_id'],
                    'mime': 'audio/mpeg', 'audio_base64': base64.b64encode(b'ID3fixture').decode()}
                return httpx.Response(200, json={'status': 'FAILED' if mode == 'failure' else 'COMPLETED', 'output': output})
            client = httpx.AsyncClient
            with patch('web.character_runtime.character_route', return_value={'runpod_endpoint_id': 'fixture'}), \
                 patch('web.cloud_models.httpx.AsyncClient', side_effect=lambda **kw: client(transport=httpx.MockTransport(transport), **kw)), \
                 patch.dict(os.environ, RUNPOD_API_KEY='fixture-key', RUNPOD_WORKER_SECRET='fixture-secret', RUNPOD_TTS_TIMEOUT='2' if mode == 'transient' else '.02'):
                if mode in ('ok', 'transient'):
                    await RunPodVoiceProvider().stream(self.queue(), result.append, 'trained:mugi')
                    self.assertEqual(len(result), 1)
                    self.assertFalse(any('/cancel/' in c for c in calls))
                elif mode == 'cancel':
                    task = asyncio.create_task(RunPodVoiceProvider().stream(self.queue(), result.append, 'trained:mugi'))
                    while not any('/status/' in c for c in calls):
                        await asyncio.sleep(0)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertTrue(any('/cancel/' in c for c in calls))
                    self.assertEqual(result, [])
                else:
                    with self.assertRaises((ValueError, RuntimeError, TimeoutError)):
                        await RunPodVoiceProvider().stream(self.queue(), result.append, 'trained:mugi')
                    self.assertTrue(any('/cancel/' in c for c in calls))
                    self.assertEqual(result, [])
                self.assertEqual(sum(c.endswith('/run') for c in calls), 1)
        asyncio.run(run())

    def test_voice_success(self):
        self.execute_voice('ok')

    def test_transient_poll_retry_does_not_resubmit_job(self):
        self.execute_voice('transient')

    def test_role_isolation(self):
        self.execute_voice('wrong-role')

    def test_failed_job_cancelled_without_resubmission(self):
        self.execute_voice('failure')

    def test_timeout_cancels_remote_job(self):
        self.execute_voice('timeout')

    def test_user_cancel_cancels_remote_job(self):
        self.execute_voice('cancel')

    def test_dashscope_native_stream(self):
        async def run():
            def transport(request):
                data = json.loads(request.content)
                self.assertTrue(data['parameters']['incremental_output'])
                self.assertEqual(data['model'], 'custom-fixture')
                return httpx.Response(200, text='data: {"output":{"choices":[{"message":{"content":"你好"}}]}}\n\n',
                                      headers={'Content-Type': 'text/event-stream'})
            client = httpx.AsyncClient
            with patch.dict(os.environ, DASHSCOPE_API_KEY='fixture'), patch('web.cloud_models.httpx.AsyncClient',
                side_effect=lambda **kw: client(transport=httpx.MockTransport(transport), **kw)):
                chunks = [c async for c in DashScopeCustomChat(model_id='custom-fixture')._astream([HumanMessage('你好')])]
                reply = await DashScopeCustomChat(model_id='custom-fixture').ainvoke([HumanMessage('你好')])
                self.assertEqual(reply.content, '你好')
            self.assertEqual(chunks[0].message.content, '你好')
        asyncio.run(run())


class WorkerSecurityTests(SimpleTestCase):
    def setUp(self):
        source = Path(settings.BASE_DIR).parent / 'deploy/cloud/tts/worker.py'
        spec = importlib.util.spec_from_file_location('tts_worker_fixture', source)
        self.worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.worker)
        self.payload = {'role': 'mugi', 'text': '你好', 'request_id': 'fixture', 'timestamp': int(time.time())}
        message = json.dumps(self.payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        self.payload['signature'] = hmac.new(b'fixture', message, hashlib.sha256).hexdigest()

    def test_authentication_and_tamper_rejection(self):
        with patch.dict(os.environ, WORKER_SHARED_SECRET='fixture'):
            self.worker.authenticate(self.payload)
            self.payload['role'] = 'hotaru'
            with self.assertRaises(ValueError):
                self.worker.authenticate(self.payload)

    def test_expired_and_unknown_role_rejected(self):
        with patch.dict(os.environ, WORKER_SHARED_SECRET='fixture'):
            self.payload['timestamp'] = 1
            with self.assertRaises(ValueError):
                self.worker.authenticate(self.payload)
            self.payload['role'] = '../mugi'
            with self.assertRaises(ValueError):
                self.worker.authenticate(self.payload)

    def test_duplicate_cached_before_gpu_import(self):
        with patch.dict(os.environ, WORKER_SHARED_SECRET='fixture'):
            digest = self.worker.authenticate(self.payload)
            self.worker.CACHE['fixture'] = (time.time(), digest, {'role': 'mugi', 'cached': True})
            self.assertTrue(self.worker.handler({'input': self.payload})['cached'])

    def test_duplicate_identifier_cannot_cross_roles(self):
        with patch.dict(os.environ, WORKER_SHARED_SECRET='fixture'):
            self.worker.CACHE['fixture'] = (time.time(), 'other-request-digest', {})
            with self.assertRaises(ValueError):
                self.worker.handler({'input': self.payload})

    def test_failed_weight_switch_resets_engine_and_cannot_return_wrong_voice(self):
        import numpy as np
        from unittest.mock import Mock
        worker = self.worker
        engine = Mock()
        engine.run.return_value = [(32000, np.zeros(32, dtype=np.int16))]
        constructor = Mock(return_value=engine)
        config_factory = Mock(side_effect=lambda data: SimpleNamespace(data=data))
        cuda = Mock()
        cuda.is_available.return_value = True
        cuda.mem_get_info.return_value = (8 * 1024**3, 16 * 1024**3)
        temporary_root = Path(settings.BASE_DIR).parent / 'runtime/test-tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            root = Path(directory)
            plan = {'characters': {r: {'s1_weights': r + '-s1', 's2_weights': r + '-s2',
                'reference_audio': r + '.wav', 'reference_text': 'こんにちは'} for r in worker.ROLES}}
            (root / 'manifest.json').write_text(json.dumps(plan), encoding='utf-8')
            for role in worker.ROLES:
                (root / (role + '-tts.yaml')).write_text('{"custom": {}}')
            with patch.dict(os.environ, WORKER_SHARED_SECRET='fixture', MODEL_ROOT=directory), \
                 patch.dict('sys.modules', {'torch': SimpleNamespace(cuda=cuda),
                    'GPT_SoVITS.TTS_infer_pack.TTS': SimpleNamespace(TTS=constructor, TTS_Config=config_factory)}), \
                 patch.object(worker.subprocess, 'run', return_value=SimpleNamespace(stdout=b'ID3fixture')):
                def request(role, ident):
                    data = {'role': role, 'text': '你好', 'request_id': ident, 'timestamp': int(time.time())}
                    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
                    data['signature'] = hmac.new(b'fixture', raw, hashlib.sha256).hexdigest()
                    return worker.handler({'input': data})
                self.assertEqual(request('mugi', 'one')['role'], 'mugi')
                self.assertEqual(constructor.call_args.args[0].configs_path, '/tmp/ailover-current-tts.yaml')
                engine.init_vits_weights.side_effect = RuntimeError('simulated out of memory')
                with self.assertRaises(RuntimeError):
                    request('hotaru', 'two')
                self.assertIsNone(worker.ENGINE)
                self.assertIsNone(worker.CURRENT)
                cuda.empty_cache.assert_called_once()
                engine.init_vits_weights.side_effect = None
                self.assertEqual(request('hotaru', 'three')['role'], 'hotaru')
                self.assertEqual(worker.CURRENT, 'hotaru')
                self.assertEqual(constructor.call_count, 2)
                self.assertEqual((root / 'mugi-tts.yaml').read_text(), '{"custom": {}}')
