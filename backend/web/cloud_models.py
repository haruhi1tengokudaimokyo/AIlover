"""Remote adapters: credentials stay in backend environment, never in job logs."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, AIMessage
from langchain_core.outputs import ChatGenerationChunk, ChatGeneration, ChatResult


def secret(name):
    value = os.getenv(name, '')
    if not value:
        raise ValueError('Missing backend credential: ' + name)
    return value


class DashScopeCustomChat(BaseChatModel):
    model_id: str
    key_env: str = 'DASHSCOPE_API_KEY'
    endpoint: str = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'

    @property
    def _llm_type(self):
        return 'dashscope-custom-model'

    def _generate(self, *args, **kwargs):
        raise NotImplementedError('Use asynchronous streamed character generation')

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        content = ''
        async for chunk in self._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            content += chunk.message.content
            if run_manager:
                await run_manager.on_llm_new_token(chunk.message.content, chunk=chunk)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        roles = {'human': 'user', 'ai': 'assistant', 'system': 'system'}
        payload = {'model': self.model_id, 'input': {'messages': [
            {'role': roles[m.type], 'content': m.content} for m in messages]},
            'parameters': {'result_format': 'message', 'incremental_output': True,
                           'max_tokens': 1000, 'temperature': .8}}
        if stop:
            payload['parameters']['stop'] = stop
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10), trust_env=False) as client:
            async with client.stream('POST', self.endpoint, json=payload, headers={
                'Authorization': 'Bearer ' + secret(self.key_env), 'X-DashScope-SSE': 'enable'}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    data = json.loads(line[5:])
                    if data.get('code'):
                        raise RuntimeError('Custom text service rejected request')
                    for choice in data.get('output', {}).get('choices', []):
                        content = choice.get('message', {}).get('content', '')
                        if content:
                            yield ChatGenerationChunk(message=AIMessageChunk(content=content))


class RunPodVoiceProvider:
    async def stream(self, texts, emit, voice):
        from web.character_runtime import character_route
        role = voice.removeprefix('trained:')
        route = character_route(role)
        endpoint = route['runpod_endpoint_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', endpoint):
            raise ValueError('Invalid endpoint identifier')
        headers = {'Authorization': 'Bearer ' + secret(route.get('tts_key_env', 'RUNPOD_API_KEY'))}
        signing = secret(route.get('worker_secret_env', 'RUNPOD_WORKER_SECRET'))
        url = 'https://api.runpod.ai/v2/' + endpoint
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            while True:
                sentence = await texts.get()
                if sentence is None:
                    return
                payload = {'role': role, 'text': sentence.text, 'request_id': uuid.uuid4().hex, 'timestamp': int(time.time())}
                canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
                payload['signature'] = hmac.new(signing.encode(), canonical, hashlib.sha256).hexdigest()
                job_id, complete = None, False
                try:
                    async with asyncio.timeout(float(os.getenv('RUNPOD_TTS_TIMEOUT', '240'))):
                        # Do not retry a possibly accepted POST and create duplicate paid jobs.
                        response = await client.post(url + '/run', headers=headers, json={'input': payload})
                        response.raise_for_status()
                        received_id = response.json()['id']
                        if not isinstance(received_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', received_id):
                            raise ValueError('Invalid job identifier')
                        job_id = received_id
                        while True:
                            for attempt in range(3):
                                try:
                                    result = await client.get(url + '/status/' + job_id, headers=headers)
                                    result.raise_for_status()
                                    break
                                except httpx.HTTPStatusError as exc:
                                    if attempt == 2 or (exc.response.status_code != 429 and exc.response.status_code < 500):
                                        raise
                                except httpx.TransportError:
                                    if attempt == 2:
                                        raise
                                await asyncio.sleep(.5 * (attempt + 1))
                            data = result.json()
                            if data['status'] == 'COMPLETED':
                                output = data['output']
                                if output.get('role') != role or output.get('request_id') != payload['request_id'] or output.get('mime') != 'audio/mpeg':
                                    raise ValueError('Cross-role or invalid audio response')
                                encoded = output['audio_base64']
                                if len(encoded) > 16 * 1024**2:
                                    raise ValueError('Audio response too large')
                                audio = base64.b64decode(encoded, validate=True)
                                if not (audio.startswith(b'ID3') or audio[:1] == b'\xff'):
                                    raise ValueError('Invalid MP3 payload')
                                emit({'audio': encoded})
                                complete = True
                                break
                            if data['status'] in ('FAILED', 'CANCELLED', 'TIMED_OUT'):
                                raise RuntimeError('Remote voice job failed')
                            await asyncio.sleep(.5)
                finally:
                    if job_id and not complete:
                        async def cancel_job():
                            try:
                                async with asyncio.timeout(3):
                                    await client.post(url + '/cancel/' + job_id, headers=headers)
                            except (httpx.HTTPError, TimeoutError):
                                pass
                        await asyncio.shield(cancel_job())
