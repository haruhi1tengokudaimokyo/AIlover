from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from web.models.friend import Message
from web.views.friend.message.manage import owned_friend


class GetHistoryView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        friend = owned_friend(request, request.query_params.get('friend_id'))
        try:
            raw = request.query_params.get('last_message_id', '0')
            if not raw.isdigit() or len(raw) > 18:
                return Response({'result': '消息游标不正确'}, status=400)
            last_message_id = int(raw)
            queryset = Message.objects.filter(friend=friend)
            if last_message_id > 0 :
                queryset = queryset.filter(pk__lt=last_message_id)
            messages_raw = queryset.order_by('-id')[:10]
            messages = []
            for m in messages_raw:
                messages.append({
                    'id': m.id,
                    'user_message': m.user_message,
                    'output': m.output,
                })
            return Response({
                'result': 'success',
                'messages': messages,
            })
        except:
            return Response({
                'result': '系统异常，请稍后重试',
            })
