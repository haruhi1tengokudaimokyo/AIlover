"""Sentence buffering and replaceable cloud TTS transport; no training."""
import asyncio
import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
import websockets


class GPTSoVITSProvider:
    """Dedicated per-role upstreams; no global weight switching across users."""
    async def stream(self, texts, emit, voice):
        import httpx
        from web.character_runtime import character_route
        slug = voice.removeprefix('trained:')
        route = character_route(slug)
        if not route or not voice.startswith('trained:'):
            raise ValueError('Unknown trained voice')
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            while True:
                item = await texts.get()
                if item is None:
                    return
                wait = (time.monotonic() - item.queued_at) * 1000
                texts.metrics['queue_wait_count'] += 1
                texts.metrics['queue_wait_total_ms'] += wait
                texts.metrics['queue_wait_max_ms'] = max(texts.metrics['queue_wait_max_ms'], wait)
                response = await client.post(route['tts_url'].rstrip('/') + '/tts', json={
                    'text': item.text, 'text_lang': 'zh', 'prompt_lang': 'ja',
                    'prompt_text': route['reference_text'], 'ref_audio_path': route['reference_audio'],
                    'media_type': 'wav', 'streaming_mode': False, 'batch_size': 1,
                    'text_split_method': 'cut0', 'seed': 20261028})
                response.raise_for_status()
                wav = response.content
                if len(wav) > 32 * 1024 * 1024 or not wav.startswith(b'RIFF'):
                    raise RuntimeError('Invalid TTS audio response')
                # Existing browser MSE player expects MP3, never relabel WAV bytes.
                executable = os.getenv('FFMPEG_BIN')
                if not executable:
                    try:
                        from imageio_ffmpeg import get_ffmpeg_exe
                        executable = get_ffmpeg_exe()
                    except ImportError:
                        executable = 'ffmpeg'
                process = await asyncio.create_subprocess_exec(executable,
                    '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0', '-f', 'mp3', 'pipe:1',
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    async with asyncio.timeout(30):
                        audio, error = await process.communicate(wav)
                    if process.returncode or not audio:
                        raise RuntimeError('TTS audio encoding failed')
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                emit({'audio': base64.b64encode(audio).decode('ascii')})


class SentenceBuffer:
    def __init__(self, minimum=4, maximum=80):
        if not 1 <= minimum <= maximum <= 300:
            raise ValueError('invalid_sentence_limits')
        self.minimum, self.maximum, self.pending = minimum, maximum, ''

    def feed(self, text):
        result = []
        for char in text:
            self.pending += char
            if len(self.pending) >= self.maximum or (char in '。！？!?；;\n' and len(self.pending) >= self.minimum):
                result.append(self.pending)
                self.pending = ''
        return result

    def flush(self):
        value, self.pending = self.pending, ''
        return [value] if value else []


@dataclass
class Sentence:
    text: str
    queued_at: float


class SentenceQueue(asyncio.Queue):
    def __init__(self, metrics, enabled=True, maximum=32):
        super().__init__(maxsize=maximum)
        self.metrics, self.enabled, self.failed = metrics, enabled, False
        self.eof_consumed = False

    async def get(self):
        item = await super().get()
        if item is None:
            self.eof_consumed = True
        return item

    def offer(self, text):
        if not self.enabled or self.failed:
            return
        try:
            self.put_nowait(Sentence(text, time.monotonic()))
            self.metrics['sentence_count'] += 1
        except asyncio.QueueFull:
            self.failed = True
            self.metrics['errors'].append('tts_queue_overflow')

    def finish(self):
        if not self.enabled or self.failed:
            return
        try:
            self.put_nowait(None)
        except asyncio.QueueFull:
            self.failed = True
            self.metrics['errors'].append('tts_queue_overflow')

    def clear(self):
        while not self.empty():
            self.get_nowait()


class PacketSink:
    """Producer-side timing and sequence metadata, independent of SSE consumption."""
    def __init__(self, queue, metrics, started, generation_id=None):
        self.queue, self.metrics, self.started, self.generation_id = queue, metrics, started, generation_id

    def put(self, packet):
        if not isinstance(packet, dict):
            self.queue.put(packet)
            return
        packet = dict(packet)
        elapsed = (time.monotonic() - self.started) * 1000
        if packet.get('content') and self.metrics['ttft_ms'] is None:
            self.metrics['ttft_ms'] = elapsed
        if packet.get('audio'):
            if self.metrics['ttfa_ms'] is None:
                self.metrics['ttfa_ms'] = elapsed
            packet['audio_seq'] = self.metrics['audio_chunks']
            self.metrics['audio_chunks'] += 1
        if self.generation_id:
            packet['generation_id'] = self.generation_id
        self.queue.put(packet)


class CloudTTSProvider:
    """One ordered WebSocket session per reply, with parallel send/receive."""
    async def stream(self, texts, emit, voice):
        task_id = uuid.uuid4().hex
        url = os.getenv('WSS_URL', 'wss://dashscope.aliyuncs.com/api-ws/v1/inference')
        key = os.getenv('TTS_API_KEY') or os.getenv('API_KEY')
        async with websockets.connect(url, additional_headers={'Authorization': f'Bearer {key}'},
                                      open_timeout=10, close_timeout=2, max_size=2 ** 20) as ws:
            await ws.send(json.dumps({
                'header': {'action': 'run-task', 'task_id': task_id, 'streaming': 'duplex'},
                'payload': {'task_group': 'audio', 'task': 'tts', 'function': 'SpeechSynthesizer',
                    'model': os.getenv('TTS_MODEL', 'cosyvoice-v3-flash'),
                    'parameters': {'text_type': 'PlainText', 'voice': voice, 'format': 'mp3',
                        'sample_rate': 22050, 'volume': 50, 'rate': float(os.getenv('TTS_RATE', '1.0')),
                        'pitch': float(os.getenv('TTS_PITCH', '1.0'))}, 'input': {}}
            }))
            async with asyncio.timeout(10):
                while True:
                    packet = await ws.recv()
                    if isinstance(packet, bytes):
                        raise RuntimeError('audio_before_start')
                    event = json.loads(packet).get('header', {}).get('event')
                    if event == 'task-failed':
                        raise RuntimeError('tts_start_failed')
                    if event == 'task-started':
                        break

            async def sender():
                while True:
                    item = await texts.get()
                    if item is not None:
                        wait = (time.monotonic() - item.queued_at) * 1000
                        texts.metrics['queue_wait_count'] += 1
                        texts.metrics['queue_wait_total_ms'] += wait
                        texts.metrics['queue_wait_max_ms'] = max(texts.metrics['queue_wait_max_ms'], wait)
                    await ws.send(json.dumps({
                        'header': {'action': 'finish-task' if item is None else 'continue-task',
                            'task_id': task_id, 'streaming': 'duplex'},
                        'payload': {'input': {} if item is None else {'text': item.text}}
                    }))
                    if item is None:
                        return

            async def receiver():
                while True:
                    packet = await asyncio.wait_for(ws.recv(), timeout=30)
                    if isinstance(packet, bytes):
                        emit({'audio': base64.b64encode(packet).decode('ascii')})
                    else:
                        event = json.loads(packet).get('header', {}).get('event')
                        if event == 'task-failed':
                            raise RuntimeError('tts_failed')
                        if event == 'task-finished':
                            return

            async with asyncio.TaskGroup() as group:
                group.create_task(sender())
                group.create_task(receiver())
