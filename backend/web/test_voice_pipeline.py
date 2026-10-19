import asyncio
import base64
import json
import os
import threading
import uuid
from queue import Queue
from unittest.mock import AsyncMock, patch
from unittest.mock import Mock
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from langchain_core.messages import AIMessageChunk, AIMessage, HumanMessage
from rest_framework.test import APIClient
from web.models.user import UserProfile
from web.models.character import Character
from web.models.friend import Friend, Message
from web.views.friend.message.chat.chat import MessageChatView
from web.views.friend.message.chat.voice import SentenceBuffer, SentenceQueue, CloudTTSProvider
from web.views.friend.message.chat.generation import Generation, register, cancel
from web.views.friend.message.leases import acquire


class TokenModel:
    def __init__(self, text='你好。今天过得怎么样？', delay=0):
        self.text, self.delay, self.closed, self.completed = text, delay, False, False

    async def astream(self, *args, **kwargs):
        try:
            for char in self.text:
                if self.delay:
                    await asyncio.sleep(self.delay)
                yield AIMessageChunk(content=char), {}
            self.completed = True
        finally:
            self.closed = True


class MockTTS:
    def __init__(self, delay=0):
        self.delay, self.sentences, self.closed = delay, [], False

    async def stream(self, texts, emit, voice):
        try:
            while True:
                sentence = await texts.get()
                if sentence is None:
                    return
                self.sentences.append(sentence.text)
                await asyncio.sleep(self.delay)
                emit({'audio': base64.b64encode(b'synthetic-not-mp3').decode()})
        finally:
            self.closed = True


class BufferTests(SimpleTestCase):
    def test_langgraph_uses_async_llm_for_streaming_and_preserves_sync_eval(self):
        from web.views.friend.message.chat.graph import ChatGraph
        llm = Mock()
        llm.ainvoke = AsyncMock(return_value=AIMessage('synthetic'))
        llm.invoke.return_value = AIMessage('synthetic')
        with patch('web.views.friend.message.chat.graph.ChatOpenAI') as create:
            create.return_value.root_async_client.close = AsyncMock()
            create.return_value.bind_tools.return_value = llm
            app = ChatGraph.create_app()
            asyncio.run(app.ainvoke({'messages': [HumanMessage('fixture')]}))
            llm.ainvoke.assert_awaited_once()
            llm.invoke.assert_not_called()
            app.invoke({'messages': [HumanMessage('fixture')]})
            llm.invoke.assert_called_once()
            asyncio.run(ChatGraph.close_app(app))
            create.return_value.root_async_client.close.assert_awaited_once()
            create.return_value.root_client.close.assert_called_once()

    def test_langgraph_async_request_receives_cancellation(self):
        from web.views.friend.message.chat.graph import ChatGraph
        async def run():
            began, cleaned = asyncio.Event(), asyncio.Event()
            async def request(*args):
                began.set()
                try:
                    await asyncio.sleep(2)
                finally:
                    cleaned.set()
            llm = Mock()
            llm.ainvoke = AsyncMock(side_effect=request)
            with patch('web.views.friend.message.chat.graph.ChatOpenAI') as create:
                create.return_value.root_async_client.close = AsyncMock()
                create.return_value.bind_tools.return_value = llm
                app = ChatGraph.create_app()
                task = asyncio.create_task(app.ainvoke({'messages': [HumanMessage('fixture')]}))
                await asyncio.wait_for(began.wait(), .5)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(cleaned.is_set())
                await ChatGraph.close_app(app)
        asyncio.run(run())

    def test_incremental_sentences_and_final_fragment_preserve_text(self):
        buffer = SentenceBuffer(4, 12)
        text = '你好！今天过得怎么样？没有标点的最后片段很长'
        pieces = [sentence for char in text for sentence in buffer.feed(char)] + buffer.flush()
        self.assertEqual(''.join(pieces), text)
        self.assertTrue(all(len(piece) <= 12 for piece in pieces))
        self.assertLess(len(pieces), len(text))
        self.assertEqual(buffer.flush(), [])

    def test_queue_bound_and_disabled_audio_are_nonblocking(self):
        metrics = Generation(None, '').metrics
        queue = SentenceQueue(metrics, maximum=1)
        queue.offer('first'); queue.offer('second'); queue.finish()
        self.assertTrue(queue.failed)
        self.assertEqual(queue.qsize(), 1)
        self.assertIn('tts_queue_overflow', metrics['errors'])
        queue.clear()
        self.assertTrue(queue.empty())
        queue = SentenceQueue(metrics, enabled=False)
        queue.offer('not queued'); queue.finish()
        self.assertTrue(queue.empty())

    def test_slow_tts_does_not_block_text_and_audio_tasks_are_cleaned(self):
        async def run():
            view, provider, mq = MessageChatView(), MockTTS(.02), Queue()
            view.tts_provider = provider
            generation = Generation(None, str(uuid.uuid4()))
            await view.run_tasks(TokenModel(), {'messages': []}, mq, 'mock', True, generation.stopped, generation)
            packets = list(mq.queue)
            self.assertEqual(''.join(p.get('content', '') for p in packets), '你好。今天过得怎么样？')
            self.assertEqual(''.join(provider.sentences), '你好。今天过得怎么样？')
            self.assertLess(len(provider.sentences), len(packets))
            self.assertLess(generation.metrics['model_ms'], generation.metrics['tts_ms'])
            self.assertTrue(provider.closed)
            self.assertEqual(len(asyncio.all_tasks()), 1)
        asyncio.run(run())

    def test_cancel_propagates_to_model_tts_and_loop_has_no_orphan_tasks(self):
        async def run():
            view, provider, model = MessageChatView(), MockTTS(2), TokenModel(delay=.01)
            view.tts_provider = provider
            stopped = threading.Event()
            task = asyncio.create_task(view.run_tasks(model, {'messages': []}, Queue(), 'mock', True, stopped))
            await asyncio.sleep(.03)
            stopped.set()
            await asyncio.wait_for(task, .5)
            self.assertTrue(model.closed)
            self.assertFalse(model.completed)
            self.assertTrue(provider.closed)
            self.assertEqual(len(asyncio.all_tasks()), 1)
        asyncio.run(run())

    def test_tts_timeout_and_overflow_leave_text_complete(self):
        async def run(config):
            view, provider, mq = MessageChatView(), MockTTS(2), Queue()
            view.tts_provider = provider
            generation = Generation(None, '')
            with patch.dict(os.environ, config):
                await view.run_tasks(TokenModel('一句话。' * 10), {'messages': []}, mq, 'mock', True, generation.stopped, generation)
            self.assertEqual(''.join(p.get('content', '') for p in mq.queue), '一句话。' * 10)
            self.assertTrue(any(p.get('warning') for p in mq.queue))
            self.assertTrue(generation.metrics['errors'])
        asyncio.run(run({'TTS_TIMEOUT_SECONDS': '.01'}))
        asyncio.run(run({'TTS_QUEUE_LIMIT': '1'}))

    def test_cloud_transport_sends_sentences_and_audio_in_order(self):
        class Socket:
            def __init__(self):
                self.sent, self.packets, self.closed = [], asyncio.Queue(), False
                self.packets.put_nowait(json.dumps({'header': {'event': 'task-started'}}))
            async def __aenter__(self): return self
            async def __aexit__(self, *args): self.closed = True
            async def send(self, value):
                packet = json.loads(value)
                self.sent.append(packet)
                if packet['header']['action'] == 'continue-task':
                    self.packets.put_nowait(packet['payload']['input']['text'].encode())
                if packet['header']['action'] == 'finish-task':
                    self.packets.put_nowait(json.dumps({'header': {'event': 'task-finished'}}))
            async def recv(self): return await self.packets.get()
        async def run():
            socket, metrics = Socket(), Generation(None, '').metrics
            queue = SentenceQueue(metrics)
            queue.offer('合成句子一。'); queue.offer('合成句子二。'); queue.finish()
            packets = []
            with patch('web.views.friend.message.chat.voice.websockets.connect', return_value=socket) as connect:
                await CloudTTSProvider().stream(queue, packets.append, 'mock')
            self.assertEqual([base64.b64decode(p['audio']).decode() for p in packets], ['合成句子一。', '合成句子二。'])
            self.assertEqual([p['header']['action'] for p in socket.sent], ['run-task', 'continue-task', 'continue-task', 'finish-task'])
            self.assertEqual(metrics['queue_wait_count'], 2)
            self.assertGreaterEqual(metrics['queue_wait_max_ms'], 0)
            self.assertTrue(socket.closed)
            self.assertEqual(connect.call_args.kwargs['close_timeout'], 2)
        asyncio.run(run())

    def test_cloud_start_failure_releases_websocket(self):
        class Socket:
            closed = False
            async def __aenter__(self): return self
            async def __aexit__(self, *args): self.closed = True
            async def send(self, value): pass
            async def recv(self): return json.dumps({'header': {'event': 'task-failed'}})
        socket = Socket()
        with patch('web.views.friend.message.chat.voice.websockets.connect', return_value=socket), self.assertRaises(RuntimeError):
            asyncio.run(CloudTTSProvider().stream(SentenceQueue(Generation(None, '').metrics), lambda _: None, 'mock'))
        self.assertTrue(socket.closed)

    def test_provider_ending_before_eof_is_reported_as_degraded(self):
        async def run():
            view, mq = MessageChatView(), Queue()
            view.tts_provider = Mock(stream=AsyncMock())
            generation = Generation(None,'')
            await view.run_tasks(TokenModel(delay=.001),{'messages':[]},mq,'mock',True,generation.stopped,generation)
            self.assertTrue(any(packet.get('warning') for packet in mq.queue))
            self.assertIn('tts_unavailable',generation.metrics['errors'])
            self.assertEqual(''.join(packet.get('content','') for packet in mq.queue),'你好。今天过得怎么样？')
        asyncio.run(run())


class GenerationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='synthetic-voice')
        profile = UserProfile.objects.create(user=self.user)
        character = Character.objects.create(author=profile, name='synthetic', profile='fixture')
        self.friend = Friend.objects.create(me=profile, character=character)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def runtime(self):
        generation = Generation(self.friend.pk, str(uuid.uuid4()), acquire(self.friend.pk))
        register(generation)
        self.addCleanup(generation.close_stream)
        self.addCleanup(generation.finish)
        self.addCleanup(generation.cancel)
        return generation

    def test_wrong_generation_duplicate_stop_and_cross_user_cancel(self):
        generation = self.runtime()
        endpoint = '/api/friend/message/chat/cancel/'
        response = self.client.post(endpoint, {'friend_id': self.friend.pk, 'generation_id': str(uuid.uuid4())}, format='json')
        self.assertFalse(response.data['cancelled'])
        self.assertFalse(generation.stopped.is_set())
        self.client.force_authenticate(User.objects.create_user(username='synthetic-other-voice'))
        self.assertEqual(self.client.post(endpoint, {'friend_id': self.friend.pk, 'generation_id': generation.id}, format='json').status_code, 404)
        self.client.force_authenticate(self.user)
        for _ in range(2):
            response = self.client.post(endpoint, {'friend_id': self.friend.pk, 'generation_id': generation.id}, format='json')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data['cleanup_complete'])
        self.assertTrue(generation.done.is_set())

    def test_lock_waits_for_both_worker_and_stream_completion(self):
        generation = self.runtime()
        generation.activate(); generation.finish()
        self.assertFalse(generation.done.is_set())
        self.assertIsNone(acquire(self.friend.pk))
        generation.close_stream()
        lease = acquire(self.friend.pk)
        self.assertIsNotNone(lease)
        generation.cancel()
        self.assertIsNone(acquire(self.friend.pk))
        lease.release()

    def test_sse_audio_sequence_metrics_and_no_voice_calls_in_text_mode(self):
        view = MessageChatView()
        view.tts_provider = MockTTS()
        packets = list(view.event_stream(TokenModel(), {'messages': [HumanMessage('fixture')]}, self.friend, 'fixture', True))
        data = [json.loads(p[6:]) for p in packets if p.startswith('data: ') and '[DONE]' not in p]
        ident = data[0]['generation_id']
        audio = [p for p in data if 'audio' in p]
        self.assertEqual([p['audio_seq'] for p in audio], list(range(len(audio))))
        self.assertTrue(all(p['generation_id'] == ident for p in audio))
        metric = next(p['metrics'] for p in data if 'metrics' in p)
        self.assertTrue(metric['cleanup_complete'])
        self.assertFalse(metric['cancelled'])
        self.assertIsNotNone(metric['ttft_ms'])
        self.assertIsNotNone(metric['ttfa_ms'])
        self.assertEqual(Message.objects.count(), 1)
        with patch.object(view, 'stream_voice', new_callable=AsyncMock) as voice:
            list(view.event_stream(TokenModel(), {'messages': []}, self.friend, 'fixture', False))
        voice.assert_not_called()

    def test_disconnect_discards_partial_reply_and_cleans_worker(self):
        generation = self.runtime()
        stream = MessageChatView().event_stream(TokenModel(delay=.01), {'messages': []}, self.friend, 'fixture', False, generation=generation)
        next(stream)
        stream.close()
        self.assertTrue(generation.done.wait(.5))
        self.assertEqual(Message.objects.count(), 0)
        self.assertTrue(generation.metrics['cancelled'])

    def test_used_id_rejected_and_invalid_id_returns400(self):
        generation = self.runtime(); generation.cancel()
        with patch.dict(os.environ, {'API_KEY': 'offline-mock'}):
            response = self.client.post('/api/friend/message/chat/', {'friend_id': self.friend.pk, 'message': 'fixture', 'generation_id': generation.id}, format='json')
        self.assertEqual(response.status_code, 409)
        response = self.client.post('/api/friend/message/chat/', {'friend_id': self.friend.pk, 'message': 'fixture', 'generation_id': []}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_worker_start_failure_does_not_leak_lease(self):
        generation = self.runtime()
        with patch('threading.Thread.start', side_effect=RuntimeError):
            packets = list(MessageChatView().event_stream(TokenModel(), {'messages': []}, self.friend, 'fixture', False, generation=generation))
        self.assertTrue(any('error' in p for p in packets))
        self.assertTrue(generation.done.is_set())
        lease = acquire(self.friend.pk)
        self.assertIsNotNone(lease)
        lease.release()

    def test_unexpected_model_cancellation_does_not_save_partial_text(self):
        class CancelledModel:
            async def astream(self,*args,**kwargs):
                yield AIMessageChunk(content='partial'),{}
                raise asyncio.CancelledError()
        packets = list(MessageChatView().event_stream(CancelledModel(),{'messages':[]},self.friend,'fixture',False))
        self.assertTrue(any('error' in packet for packet in packets))
        self.assertEqual(Message.objects.count(),0)
