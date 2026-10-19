import asyncio
import json
import os
import uuid

import websockets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

class ASRView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        audio = request.FILES.get('audio')
        if not audio:
            return Response({
                'result': '音频不存在'
            })
        if audio.size > 10 * 1024 * 1024:
            return Response({'result': '音频过大，请缩短录音'}, status=400)
        pcm_data = audio.read()
        try:
            text = asyncio.run(self.run_asr_tasks(pcm_data))
        except Exception:
            return Response({'result': '语音识别失败，请检查语音密钥、网络或使用文字输入'}, status=502)
        return Response({
            'result': 'success',
            'text': text,
        })

    async def asr_sender(self, pcm_data, ws, task_id):
        chunk=32000
        for i in range(0, len(pcm_data), chunk):
            await ws.send(pcm_data[i:i+chunk])
            await asyncio.sleep(0.01)
        await ws.send(json.dumps({
            "header": {
                "action": "finish-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {
                "input": {}
            }
        }))

    async def asr_receiver(self, ws):
        text = ''
        async for msg in ws:
            data = json.loads(msg)
            event = data['header']['event']
            if event == 'result-generated':
                output = data['payload']['output']
                if output.get('transcription', None) and output['transcription']['sentence_end']:
                    text += output['transcription']['text']
            elif event == 'task-failed':
                raise RuntimeError('语音识别服务返回失败')
            elif event == 'task-finished':
                break
        return text



    async def run_asr_tasks(self, pcm_data):
        task_id = uuid.uuid4().hex
        api_key = os.getenv('TTS_API_KEY') or os.getenv('API_KEY')
        wss_url = os.getenv('WSS_URL', 'wss://dashscope.aliyuncs.com/api-ws/v1/inference')
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        async with asyncio.timeout(60), websockets.connect(wss_url, additional_headers=headers, open_timeout=10) as ws:
            await ws.send(json.dumps({
                "header": {
                    "streaming": "duplex",
                    "task_id": task_id,
                    "action": "run-task"
                },
                "payload": {
                    "model": "gummy-realtime-v1",
                    "parameters": {
                        "sample_rate": 16000,
                        "format": "pcm",
                        "transcription_enabled": True,
                    },
                    "input": {},
                    "task": "asr",
                    "task_group": "audio",
                    "function": "recognition"
                }
            }))
            async for msg in ws:
                event = json.loads(msg)['header']['event']
                if event == 'task-failed':
                    raise RuntimeError('语音识别启动失败')
                if event == 'task-started':
                    break
            _, text = await asyncio.gather(
                self.asr_sender(pcm_data, ws, task_id),
                self.asr_receiver(ws),
            )
            return text
