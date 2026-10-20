from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from web.models.friend import Friend
from web.views.friend.get_or_create import _character_payload


class GetSingleFriendView(APIView):
    """按 friend_id 取单个好友 + 角色完整 payload（/chat/:friendId 工作区的数据源）。

    语义：未登录 401/403（DRF IsAuthenticated）；编号非法 400；
    好友不存在 404；存在但归属他人 403。
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        raw = request.query_params.get('friend_id', '')
        if isinstance(raw, bool) or not str(raw).isdigit() or len(str(raw)) > 18:
            return Response({'result': '好友编号不正确'}, status=400)
        friend = Friend.objects.select_related(
            'character__author__user', 'me__user',
        ).filter(pk=raw).first()
        if friend is None:
            return Response({'result': '好友不存在'}, status=404)
        if friend.me.user_id != request.user.id:
            return Response({'result': '无权访问该好友'}, status=403)
        return Response({
            'result': 'success',
            'friend': {
                'id': friend.id,
                'character': _character_payload(friend.character),
            },
        })
