import uuid
from django.http import Http404
from django.utils.timezone import now
from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from web.documents.utils import debug_trace
from web.documents.utils.story_retriever import read_channel
from web.models.friend import MemoryItem, Message
from web.views.friend.message.manage import owned_friend


class DebugEvidenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not debug_trace.enabled():
            raise Http404
        friend = owned_friend(request, request.query_params.get('friend_id'))
        try:
            ident = str(uuid.UUID(request.query_params.get('generation_id', '')))
        except (ValueError, TypeError, AttributeError):
            return Response({'result': '生成标识不正确'}, status=400)
        snapshot = debug_trace.read(friend.pk, ident)
        if snapshot is None:
            raise Http404
        trace = snapshot['trace']
        injected = trace.get('context', {}).get('injected_ids', {})
        evidence = {'lore': [], 'style': [], 'memory': []}
        for channel in ('lore', 'style'):
            ids = set(injected.get(channel, []))
            try:
                rows = read_channel(channel)
            except (ValueError, OSError, TypeError):
                rows = []
            for row in rows:
                characters = row.get('characters') or [row.get('character')]
                if row['id'] in ids and friend.character.slug in characters:
                    evidence[channel].append({key: row.get(key) for key in ('id', 'text', 'context', 'source_file', 'source_location', 'route_id', 'scene_id')})
        ids = [int(value.split(':')[1]) for value in injected.get('memory', [])
               if isinstance(value, str) and value.startswith('memory:') and value.split(':')[1].isdigit()]
        items = MemoryItem.objects.filter(friend=friend, pk__in=ids, status='active').filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now()))
        # Re-check live status: a forgotten item must not remain accessible via old traces.
        for item in items:
            source = Message.objects.filter(friend=friend, pk=item.source_message_id).first()
            evidence['memory'].append({'id': item.pk, 'text': item.content.get('text', ''), 'version': item.version,
                                      'injected_version': trace.get('context', {}).get('memory_versions', {}).get(f'memory:{item.pk}'),
                                      'kind': item.kind, 'manual': item.manual,
                                      'source': {'id': source.pk, 'user_message': source.user_message} if source else None})
        response = Response({'result': 'success', 'generation_id': ident, **snapshot, 'evidence': evidence,
                             'notice': '资料从当前数据集读取；若构建或记忆已变化，与当时注入版本可能不同。'})
        response['Cache-Control'] = 'no-store'
        return response
