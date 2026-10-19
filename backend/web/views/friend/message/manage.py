import json
from django.db import transaction
from django.db.models import F, Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from web.models.friend import Friend, Message, MemoryItem, MemoryJob
from web.views.friend.message.memory.structured import (
    structured_enabled, invalidate, forget_items, edit_item, delete_item, MemoryConflict)
from web.views.friend.message.leases import acquire


def owned_friend(request, value):
    if isinstance(value, bool) or not str(value).isdigit() or len(str(value)) > 18:
        raise ValidationError({'result': '好友编号不正确'})
    return get_object_or_404(Friend.objects.select_related('character'), pk=value, me__user=request.user)


def memory_payload(friend):
    return {'result': 'success', 'memory': friend.memory or '',
            'enabled': friend.memory_enabled, 'revision': friend.memory_revision,
            'mode': 'structured' if structured_enabled() else 'legacy',
            'legacy_retired': friend.memory_legacy_retired}


class MemoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(memory_payload(owned_friend(request, request.query_params.get('friend_id'))))

    def patch(self, request):
        friend = owned_friend(request, request.data.get('friend_id'))
        memory = request.data.get('memory')
        enabled = request.data.get('enabled')
        revision = request.data.get('revision')
        if not isinstance(memory, str) or len(memory) > 5000 or not isinstance(enabled, bool) or type(revision) is not int or revision < 0:
            return Response({'result': '记忆最多5000字，请同时提交自动记忆开关和版本号'}, status=400)
        clear_all = request.data.get('clear_all', False)
        if not isinstance(clear_all, bool):
            return Response({'result': '清空参数不正确'}, status=400)
        restore_legacy = request.data.get('restore_legacy', False)
        if not isinstance(restore_legacy, bool) or (restore_legacy and (not memory.strip() or clear_all)):
            return Response({'result': '恢复旧摘要需明确提交审核后的非空正文'}, status=400)
        try:
            with transaction.atomic():
                invalidate(friend.pk, revision, memory=memory.strip(), memory_enabled=enabled,
                           memory_legacy_retired=(friend.memory_legacy_retired and not restore_legacy) or clear_all or (not enabled and not memory.strip()))
                if clear_all or (not enabled and not memory.strip()):
                    floor = forget_items(friend)
                    Friend.objects.filter(pk=friend.pk).update(memory_floor=floor)
        except MemoryConflict:
            return Response({'result': '记忆已更新，请重新读取后再保存'}, status=409)
        friend.refresh_from_db()
        return Response(memory_payload(friend))


def item_payload(item):
    return {'id': item.pk, 'kind': item.kind, 'key': item.key, 'content': item.content,
            'version': item.version, 'manual': item.manual, 'source_message_id': item.source_message_id,
            'expires_at': item.expires_at.isoformat() if item.expires_at else None,
            'update_time': item.update_time.isoformat()}


class MemoryItemsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        friend = owned_friend(request, request.query_params.get('friend_id'))
        before = request.query_params.get('before', '0')
        if not before.isdigit() or len(before) > 18:
            return Response({'result': '分页编号不正确'}, status=400)
        rows = MemoryItem.objects.filter(friend=friend, status='active').filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now()))
        if int(before):
            rows = rows.filter(pk__lt=int(before))
        rows = list(rows.order_by('-pk')[:51])
        return Response({'result': 'success', 'items': [item_payload(r) for r in rows[:50]],
                         'has_more': len(rows) > 50, 'revision': friend.memory_revision})

    def post(self, request):
        import hashlib
        from web.views.friend.message.memory.structured import _change, extract_explicit
        friend = owned_friend(request, request.data.get('friend_id'))
        text, kind, revision = request.data.get('text'), request.data.get('kind'), request.data.get('revision')
        if (not isinstance(text, str) or not text.strip() or len(text) > 500
                or kind not in ('semantic', 'episodic', 'state') or type(revision) is not int or revision < 0):
            return Response({'result': '需要记忆类型、1到500字正文和当前版本'}, status=400)
        text = text.strip()
        facts = extract_explicit(text)
        canonical = facts[0] if len(facts) == 1 and facts[0]['kind'] == kind else None
        key = canonical['key'] if canonical else 'manual:' + hashlib.sha256((kind + ':' + text).encode()).hexdigest()[:32]
        content = canonical['content'] if canonical else {'text': text}
        try:
            with transaction.atomic():
                invalidate(friend.pk, revision, memory_legacy_retired=True)
                item, created = MemoryItem.objects.get_or_create(friend=friend, key=key, defaults={
                    'kind': kind, 'content': content, 'manual': True})
                if not created:
                    item.status, item.content, item.manual = 'active', content, True
                    item.source_message, item.confidence = None, None
                    item.version += 1
                    item.update_time = now()
                    item.save()
                _change(item, 'manual_add', actor='manual')
        except MemoryConflict:
            return Response({'result': '记忆已变化，请重新读取'}, status=409)
        friend.refresh_from_db()
        return Response({'result': 'success', 'item': item_payload(item), 'revision': friend.memory_revision})

    def _mutate(self, request, deleting=False):
        friend = owned_friend(request, request.data.get('friend_id'))
        ident, revision = request.data.get('id'), request.data.get('revision')
        if type(ident) is not int or type(revision) is not int or ident < 1 or revision < 0:
            return Response({'result': '需要记忆编号和当前版本'}, status=400)
        item = get_object_or_404(MemoryItem, pk=ident, friend=friend, status='active')
        try:
            if deleting:
                delete_item(friend, item, revision)
            else:
                edit_item(friend, item, request.data.get('text'), revision)
        except ValueError:
            return Response({'result': '记忆正文需为1到500字'}, status=400)
        except MemoryConflict:
            return Response({'result': '记忆已变化，请重新读取'}, status=409)
        friend.refresh_from_db()
        return Response({'result': 'success', 'revision': friend.memory_revision})

    def patch(self, request):
        return self._mutate(request)

    def delete(self, request):
        return self._mutate(request, deleting=True)


class MemorySourceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        friend = owned_friend(request, request.query_params.get('friend_id'))
        ident = request.query_params.get('id', '')
        if not ident.isdigit() or len(ident) > 18:
            return Response({'result': '记忆编号不正确'}, status=400)
        item = get_object_or_404(MemoryItem, pk=ident, friend=friend, status='active')
        source = Message.objects.filter(pk=item.source_message_id, friend=friend).first()
        return Response({'result': 'success', 'source': {'id': source.pk, 'user_message': source.user_message,
                         'create_time': source.create_time.isoformat()} if source else None,
                         'changes': list(item.changes.order_by('-pk').values('version', 'action', 'actor', 'create_time')[:20])})


class HistorySearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        friend = owned_friend(request, request.query_params.get('friend_id'))
        query = request.query_params.get('q', '').strip()
        before = request.query_params.get('before', '0')
        if not query or len(query) > 200 or not before.isdigit() or len(before) > 18:
            return Response({'result': '请输入1到200字的关键词'}, status=400)
        rows = Message.objects.filter(friend=friend).filter(Q(user_message__icontains=query) | Q(output__icontains=query))
        if int(before):
            rows = rows.filter(pk__lt=int(before))
        rows = list(rows.order_by('-id')[:21])
        results = [{'id': row.pk, 'user_message': row.user_message, 'output': row.output,
                    'create_time': row.create_time.isoformat()} for row in rows[:20]]
        return Response({'result': 'success', 'messages': results, 'has_more': len(rows) > 20})


class HistoryExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        friend = owned_friend(request, request.query_params.get('friend_id'))
        # 固定导出边界，导出期间新增的消息不进入本次文件。
        last = Message.objects.filter(friend=friend).order_by('-id').values_list('id', flat=True).first() or 0
        def chunks():
            yield '{"version":1,"character":' + json.dumps(friend.character.name, ensure_ascii=False)
            yield ',"memory":' + json.dumps(friend.memory or '', ensure_ascii=False) + ',"messages":['
            first = True
            for row in Message.objects.filter(friend=friend, pk__lte=last).order_by('id').iterator(chunk_size=200):
                if not first:
                    yield ','
                first = False
                yield json.dumps({'id': row.pk, 'user_message': row.user_message, 'output': row.output,
                                  'create_time': row.create_time.isoformat()}, ensure_ascii=False)
            yield '],"structured_memories":['
            first = True
            for item in MemoryItem.objects.filter(friend=friend, status='active').order_by('pk').iterator(chunk_size=200):
                if not first:
                    yield ','
                first = False
                yield json.dumps(item_payload(item), ensure_ascii=False)
            yield ']}'
        response = StreamingHttpResponse(chunks(), content_type='application/json; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="ailover-chat-{friend.pk}.json"'
        response['Cache-Control'] = 'no-store'
        return response


class HistoryClearView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        friend = owned_friend(request, request.data.get('friend_id'))
        if request.data.get('confirm') != 'CLEAR':
            return Response({'result': '需要明确确认清空历史'}, status=400)
        lease = acquire(friend.pk)
        if not lease:
            return Response({'result': '角色正在回复，请停止回复并等待连接关闭后再清空'}, status=409)
        try:
            with transaction.atomic():
                fresh = Friend.objects.get(pk=friend.pk)
                invalidate(friend.pk, fresh.memory_revision, memory='', memory_enabled=False, memory_legacy_retired=True)
                floor = forget_items(friend)
                Friend.objects.filter(pk=friend.pk).update(memory_floor=floor)
                deleted, _ = Message.objects.filter(friend=friend).delete()
            return Response({'result': 'success', 'deleted': deleted})
        finally:
            lease.release()
