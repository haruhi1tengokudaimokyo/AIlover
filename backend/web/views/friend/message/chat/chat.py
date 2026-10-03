import asyncio
import base64
import json
import os
import threading
import uuid
from queue import Queue

import websockets
from django.http import StreamingHttpResponse
from langchain_core.messages import HumanMessage, BaseMessageChunk, SystemMessage, AIMessage
from rest_framework.renderers import BaseRenderer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from web.models.friend import Friend, Message, SystemPrompt
from web.views.friend.message.chat.graph import ChatGraph
from web.views.friend.message.memory.update import update_memory


class SSERenderer(BaseRenderer):
    media_type = 'text/event-stream'
    format = 'txt'
    def render(self, data, accepted_media_type=None, renderer_context=None):
        # 错误响应是 dict/list，必须序列化，否则 Django 会把字典当迭代器逐键输出
        if isinstance(data, (dict, list)):
            return json.dumps(data, ensure_ascii=False)
        return data


def add_system_prompt(state, friend, message):
    msgs = state['messages']
    system_prompts = SystemPrompt.objects.filter(title='回复').order_by('order_number')
    prompt = ''
    for sp in system_prompts:
        prompt += sp.prompt
    prompt += f'\n【角色性格】\n{friend.character.profile}\n'
    prompt += f'【长期记忆】\n{friend.memory}\n'
    # 风格 RAG：按用户消息检索角色原作台词，作为语气/口癖参考（索引不存在时跳过）
    if friend.character.slug:
        from web.documents.utils.style_retriever import retrieve
        style_lines = retrieve(friend.character.slug, message, k=5)
        if style_lines:
            prompt += '【台词风格参考】（角色原作台词，日语原文，模仿其语感，不要照抄内容）\n'
            prompt += '\n'.join(f'・{t}' for t in style_lines) + '\n'
    return {'messages': [SystemMessage(prompt)] + msgs}


def add_recent_messages(state, friend):
    msgs = state['messages']
    message_raw = list(Message.objects.filter(friend=friend).order_by('-id')[:10])
    message_raw.reverse()
    messages = []
    for m in message_raw:
        messages.append(HumanMessage(m.user_message))
        messages.append(AIMessage(m.output))
    return {'messages': msgs[:1] + messages + msgs[-1:]}


class MessageChatView(APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [SSERenderer]
    def post(self, request):
        friend_id = request.data['friend_id']
        message = request.data['message'].strip()
        if not message:
            return Response({
                'result': '消息不能为空'
            })
        friends = Friend.objects.filter(pk=friend_id, me__user=request.user)
        if not friends.exists():
            return Response({
                'result': '好友不存在'
            })
        friend = friends.first()
        try:
            app = ChatGraph.create_app()
        except Exception:
            return Response({
                'result': '模型服务未配置或不可用，请检查 data/.env 中的 API_KEY / API_BASE 配置'
            }, status=500)

        inputs = {
            'messages': [HumanMessage(message)]
        }
        inputs = add_system_prompt(inputs, friend, message)
        inputs = add_recent_messages(inputs, friend)

        response = StreamingHttpResponse(
            self.event_stream(app, inputs, friend, message),
            content_type='text/event-stream',
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response


    async def tts_sender(self, app, inputs, mq, ws, task_id):
        async for msg, metadata in app.astream(inputs, stream_mode="messages"):
            if isinstance(msg, BaseMessageChunk):
                if msg.content:
                    await ws.send(json.dumps({
                        "header": {
                            "action": "continue-task",
                            "task_id": task_id,  # 随机uuid
                            "streaming": "duplex"
                        },
                        "payload": {
                            "input": {
                                "text": msg.content,
                            }
                        }
                    }))
                    mq.put_nowait({'content': msg.content})
                if hasattr(msg, 'usage_metadata') and msg.usage_metadata:
                    mq.put_nowait({'usage': msg.usage_metadata})
        await ws.send(json.dumps({
            "header": {
                "action": "finish-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {
                "input": {}  # input不能省去，否则会报错
            }
        }))


    async def tts_receiver(self, mq, ws):
        async for msg in ws:
            if isinstance(msg, bytes):
                audio = base64.b64encode(msg).decode('utf-8')
                mq.put_nowait({'audio': audio})
            else:
                data = json.loads(msg)
                event = data['header']['event']
                if event in ['task-finished', 'task-failed']:
                    break


    async def run_tts_tasks(self, app, inputs, mq, voice):
        task_id = uuid.uuid4().hex
        api_key = os.getenv('API_KEY')
        wss_url = os.getenv('WSS_URL')
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        async with websockets.connect(wss_url, additional_headers=headers) as ws:
            await ws.send(json.dumps({
                "header": {
                    "action": "run-task",
                    "task_id": task_id,  # 随机uuid
                    "streaming": "duplex"
                },
                "payload": {
                    "task_group": "audio",
                    "task": "tts",
                    "function": "SpeechSynthesizer",
                    "model": "cosyvoice-v3-flash",
                    "parameters": {
                        "text_type": "PlainText",
                        "voice": voice,  # 音色（跟随角色配置）
                        "format": "mp3",  # 音频格式
                        "sample_rate": 22050,  # 采样率
                        "volume": 50,  # 音量
                        "rate": float(os.getenv('TTS_RATE', '1.0')),  # 语速
                        "pitch": float(os.getenv('TTS_PITCH', '1.0'))  # 音调
                    },
                    "input": {  # input不能省去，不然会报错
                    }
                }
            }))
            async for msg in ws:
                if json.loads(msg)['header']['event'] == 'task-started':
                    break
            await asyncio.gather(
                self.tts_sender(app, inputs, mq, ws, task_id),
                self.tts_receiver(mq, ws),
            )


    def work(self, app, inputs, mq, voice):
        try:
            asyncio.run(self.run_tts_tasks(app, inputs, mq, voice))
        finally:
            mq.put_nowait(None)


    def event_stream(self, app, inputs, friend, message):
        mq = Queue()
        voice = friend.character.voice or os.getenv('TTS_VOICE', 'longanyang')
        thread = threading.Thread(target=self.work, args=(app, inputs, mq, voice))
        thread.start()

        full_output = ''
        full_usage = {}
        while True:
            msg = mq.get()
            if not msg:
                break
            if msg.get('content', None):
                full_output += msg['content']
                yield f'data: {json.dumps({'content': msg['content']}, ensure_ascii=False)}\n\n'
            if msg.get('audio', None):
                yield f'data: {json.dumps({'audio': msg['audio']}, ensure_ascii=False)}\n\n'
            if msg.get('usage', None):
                full_usage = msg['usage']

        yield 'data: [DONE]\n\n'
        input_tokens = full_usage.get('input_tokens', 0)
        output_tokens = full_usage.get('output_tokens', 0)
        total_tokens = full_usage.get('total_tokens', 0)
        Message.objects.create(
            friend=friend,
            user_message=message[:2000],
            input=json.dumps(
                [m.model_dump() for m in inputs['messages']],
                ensure_ascii=False,
            )[:20000],
            output=full_output[:5000],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        # 每 5 条消息异步更新一次长期记忆，避免阻塞对话响应
        if Message.objects.filter(friend=friend).count() % 5 == 0:
            threading.Thread(target=self._safe_update_memory, args=(friend.pk,), daemon=True).start()

    @staticmethod
    def _safe_update_memory(friend_id):
        from django import db
        try:
            f = Friend.objects.filter(pk=friend_id).first()
            if f:
                update_memory(f)
        except Exception:
            pass
        finally:
            db.connections.close_all()
