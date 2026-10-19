import json
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from web.models.character import Character
from web.views.utils.photo import remove_old_photo


class UpdateCharacterView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        try:
            character_id = request.data['character_id']
            character = Character.objects.get(id=character_id, author__user=request.user)
            name = request.data['name'].strip()
            profile = request.data['profile'].strip()[:100000]
            voice = request.data.get('voice', character.voice).strip()
            greeting = request.data.get('greeting', character.greeting).strip()
            replies = request.data.get('quick_replies', character.quick_replies or '[]')
            try:
                replies = json.loads(replies) if isinstance(replies, str) else replies
                if not isinstance(replies, list) or len(replies) > 10 or any(not isinstance(text, str) or len(text) > 200 for text in replies):
                    raise ValueError()
            except (ValueError, TypeError):
                return Response({'result': '快捷话题最多10条，每条最多200字'}, status=400)
            if len(name) > 50 or len(voice) > 100 or len(greeting) > 2000:
                return Response({'result': '名称、音色或开场白过长'}, status=400)
            photo = request.FILES.get('photo',None)
            background_image = request.FILES.get('background_image',None)

            if not name:
                return Response({
                    'result':'名字不能为空'
                })
            if not profile:
                return Response({
                    'result':'角色简介不能为空'
                })
            if photo:
                remove_old_photo(character.photo)
                character.photo = photo
            if background_image:
                remove_old_photo(background_image)
                character.background_image = background_image
            character.name = name
            character.profile = profile
            character.voice = voice
            character.greeting = greeting
            character.quick_replies = json.dumps(replies, ensure_ascii=False)
            character.update_time = now()
            character.save()
            return Response({
                'result':'success',
            })
        except:
            return Response({
                'result':'系统异常，请稍后重试'
            })
