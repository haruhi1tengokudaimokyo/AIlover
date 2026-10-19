from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from web.models.friend import Friend
from web.models.user import UserProfile
import json


def _character_payload(character):
    try:
        quick_replies = json.loads(character.quick_replies or '[]')
    except (ValueError, TypeError):
        quick_replies = []
    author = character.author
    return {
        'id': character.id,
        'name': character.name,
        'profile': character.profile,
        'greeting': character.greeting or '',
        'quick_replies': quick_replies,
        'photo': character.photo.url if character.photo else '',
        'background_image': character.background_image.url if character.background_image else '',
        'author': {
            'user_id': author.user_id,
            'username': author.user.username,
            'photo': author.photo.url,
        }
    }


class GetOrCreateFriendView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self,request):
        try:
            character_id = request.data['character_id']
            user = request.user
            user_profile = UserProfile.objects.get(user=user)
            friends = Friend.objects.filter(character_id=character_id, me=user_profile)
            if friends.exists():
                friend = friends.first()
            else:
                friend = Friend.objects.create(character_id=character_id, me=user_profile)
            character = friend.character
            return Response({
                'result': 'success',
                'friend':{
                    'id': friend.id,
                    'character': _character_payload(character),
            }
        })
        except:
            return Response({
                'result': '系统异常，请稍后重试'
            })
