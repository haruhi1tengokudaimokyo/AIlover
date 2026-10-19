from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from web.models.friend import Friend
from web.views.friend.message.manage import owned_friend
from web.views.friend.message.leases import acquire


class RemoveFriendView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        friend = owned_friend(request, request.data.get('friend_id'))
        lease = acquire(friend.pk)
        if not lease:
            return Response({'result': '角色正在回复，请先停止回复'}, status=409)
        try:
            friend.delete()
            return Response({
                'result': 'success',
            })
        except:
            return Response({
                'result': '系统异常，请稍后重试'
            })
        finally:
            lease.release()
