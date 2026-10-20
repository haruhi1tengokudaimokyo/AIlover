from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from web.models.friend import Friend
from web.views.friend.get_or_create import _character_payload


class GetListFriendView(APIView):
    permission_classes = (IsAuthenticated,)
    def get(self, request):
        try:
            items_count = int(request.query_params.get('items_count', 0))
            friends_raw = Friend.objects.select_related('character__author__user').filter(
                me__user=request.user
            ).order_by('-update_time')[items_count: items_count + 20]
            friends = []
            for friend in friends_raw:
                character = friend.character
                friends.append({
                    'id': friend.id,
                    'character': _character_payload(character),
            })
            return Response({
                'result': 'success',
                'friends': friends,
            })

        except:
            return Response({
                'result': '系统异常，请稍后重试'
            })
