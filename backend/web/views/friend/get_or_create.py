from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from web.models.friend import Friend
from web.models.user import UserProfile
from web.views.friend.assets import portrait_url_for, display_asset_url_for
import json
import re


def _character_payload(character):
    try:
        quick_replies = json.loads(character.quick_replies or '[]')
    except (ValueError, TypeError):
        quick_replies = []
    if not isinstance(quick_replies, list):
        quick_replies = []
    quick_replies = [text[:200] for text in quick_replies[:8] if isinstance(text, str)]
    author = character.author
    description = re.sub(r'【[^】]*】', '', character.profile).strip().split('。')[0][:140]
    description = re.sub(r'^你是', '', description)
    return {
        'id': character.id,
        'name': character.name,
        'slug': character.slug or '',
        'profile': character.profile,
        'description': description + ('。' if description else ''),
        'greeting': character.greeting or '',
        'quick_replies': quick_replies,
        'photo': display_asset_url_for(character.slug, 'photo_url') or (character.photo.url if character.photo else ''),
        'background_image': display_asset_url_for(character.slug, 'background_url') or (character.background_image.url if character.background_image else ''),
        # 立绘等本地资产：按 slug 查 seed_assets/portrait_map.json，查不到为 None
        'assets': {
            'portrait_url': portrait_url_for(character.slug),
        },
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
