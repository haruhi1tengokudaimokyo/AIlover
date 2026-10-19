import os
from urllib.parse import urlsplit
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from web.models.friend import Friend, Message


class RuntimeStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            host = urlsplit(os.getenv('API_BASE', 'https://api.openai.com/v1')).hostname or ''
        except ValueError:
            host = '地址格式不正确'
        friends = Friend.objects.filter(me__user=request.user)
        return Response({'result': 'success', 'model': os.getenv('MODEL', 'deepseek-v3.2'),
            'model_host': host, 'model_key_configured': bool(os.getenv('API_KEY', '').strip()),
            'tts_enabled': os.getenv('TTS_ENABLED', 'true').lower() == 'true',
            'tts_key_configured': bool((os.getenv('TTS_API_KEY') or os.getenv('API_KEY', '')).strip()),
            'friend_count': friends.count(), 'message_count': Message.objects.filter(friend__in=friends).count()})
