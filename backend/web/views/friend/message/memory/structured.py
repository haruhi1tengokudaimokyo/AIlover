"""SQLite-backed memory lifecycle. No model, network, or background daemon required."""
import hashlib
import os
import re
import uuid
from datetime import timedelta
from django.db import transaction, OperationalError
from django.db.models import F, Q
from django.utils.timezone import now
from web.models.friend import Friend, Message, MemoryItem, MemoryChange, MemoryJob


class MemoryConflict(Exception):
    pass


def structured_enabled():
    return os.getenv('MEMORY_MODE', 'structured') == 'structured'


def extract_explicit(text):
    """Intentionally narrow Chinese extractor; never inspect assistant replies.

    Whole-clause matches reject quotes, hypotheticals, questions and embedded
    instructions. Unknown facts are ignored instead of being guessed.
    """
    records, correction_scope = [], False
    for fragment in re.finditer(r'([^。！？!?；;，,\n]+)([。！？!?；;，,\n]*)', text[:2000]):
        clause, punctuation = fragment[1].strip(), fragment[2]
        if any(mark in punctuation for mark in '？?'):
            correction_scope = False
            continue
        if re.match(r'^(?:说错了|更正|纠正)', clause):
            correction_scope = True
        corrected = correction_scope or bool(re.match(r'^(?:其实|现在|已经|我现在|我已经)', clause))
        if any(mark in punctuation for mark in '。！？!?\n'):
            correction_scope = False
        clause = re.sub(r'^(?:说错了|更正|纠正)[：:]?', '', clause).strip()
        name = re.fullmatch(r'(?:请)?(?:叫我|称呼我|我叫|我的名字是)([\w\u3400-\u9fff]{1,20})(?:吧)?', clause)
        if name:
            value = name[1]
            if value.endswith('吧'):
                value = value[:-1]
            if value:
                records.append(dict(kind='semantic', key='name', content={'text': f'用户希望被称呼为{value}', 'value': value}, corrected=corrected))
            continue
        preference = re.fullmatch(r'(?:其实)?我(?:(其实|现在|已经))?(不再喜欢|不喜欢|喜欢|不再喝|不喝|喝|不再吃|不吃|吃)(咖啡|茶|奶茶|牛奶|甜食|辣食|辣椒)(?:了)?', clause)
        if preference:
            aspect, verb, subject = preference.groups()
            negative = verb.startswith('不')
            records.append(dict(kind='semantic', key='preference:' + subject,
                content={'text': f'用户{verb}{subject}', 'subject': subject,
                         'value': not negative, 'expression': verb}, corrected=corrected or bool(aspect) or '不再' in verb))
            continue
        promise = re.fullmatch(r'(?:我们)?(?:约好|约定)(.{1,160})', clause)
        if promise:
            value = promise[1].strip()
            ident = hashlib.sha256(value.encode()).hexdigest()[:24]
            records.append(dict(kind='episodic', key='promise:' + ident,
                                content={'text': f'用户提出约定：{value}', 'value': value}, corrected=corrected))
            continue
        topic = re.fullmatch(r'(?:下次|稍后)聊(.{1,80})', clause)
        if topic:
            records.append(dict(kind='state', key='pending_topic', content={'text': f'待继续话题：{topic[1]}', 'value': topic[1]}, corrected=corrected))
    # Last explicit claim for each key wins within this message.
    return list({r['key']: r for r in records}.values())


def enqueue(message, expected_epoch=None):
    friend = Friend.objects.get(pk=message.friend_id)
    if expected_epoch is not None and friend.memory_epoch != expected_epoch:
        return MemoryJob.objects.get_or_create(message=message, defaults={'friend':friend, 'epoch':expected_epoch,
            'status':'cancelled', 'error_code':'request_epoch_changed'})[0]
    if not friend.memory_enabled or message.pk <= friend.memory_floor:
        return None
    return MemoryJob.objects.get_or_create(message=message, defaults={'friend': friend, 'epoch': friend.memory_epoch})[0]


def claim(job_id):
    instant, token = now(), uuid.uuid4().hex
    MemoryJob.objects.filter(pk=job_id, status='running', lease_until__lte=instant, attempts__gte=3).update(
        status='failed', error_code='lease_retry_exhausted', lease_token='', lease_until=None, update_time=instant)
    eligible = Q(status__in=['pending', 'failed'], retry_at__lte=instant, attempts__lt=3) | Q(status='running', lease_until__lte=instant, attempts__lt=3)
    changed = MemoryJob.objects.filter(pk=job_id).filter(eligible).update(status='running', lease_token=token,
        lease_until=instant + timedelta(seconds=60), attempts=F('attempts') + 1, update_time=instant)
    return token if changed else None


def _change(item, action, source=None, actor='user_message'):
    MemoryChange.objects.create(item=item, version=item.version, action=action, content=item.content,
                                source_message=source, actor=actor)


def apply_job(job_id, token, extractor=extract_explicit):
    job = MemoryJob.objects.select_related('message').get(pk=job_id)
    if job.message.friend_id != job.friend_id:
        MemoryJob.objects.filter(pk=job_id, lease_token=token, status='running').update(
            status='cancelled', lease_token='', lease_until=None, error_code='source_scope_mismatch')
        return False
    # Extraction outside the write transaction; custom extractors still need evidence validation.
    facts = extractor(job.message.user_message)
    if not isinstance(facts, list) or len(facts) > 32:
        raise ValueError('invalid_extraction')
    with transaction.atomic():
        job = MemoryJob.objects.get(pk=job_id)
        if job.status != 'running' or job.lease_token != token or not job.lease_until or job.lease_until <= now():
            return False
        friend = Friend.objects.get(pk=job.friend_id)
        if not friend.memory_enabled or friend.memory_epoch != job.epoch or job.message_id <= friend.memory_floor:
            MemoryJob.objects.filter(pk=job_id, lease_token=token).update(status='cancelled', lease_token='', lease_until=None, update_time=now())
            return False
        # CAS protects even on SQLite, where select_for_update is ineffective.
        changed = Friend.objects.filter(pk=friend.pk, memory_revision=friend.memory_revision,
            memory_epoch=job.epoch, memory_enabled=True).update(memory_revision=F('memory_revision') + 1,
                                                             memory_legacy_retired=True)
        if not changed:
            raise MemoryConflict('revision_changed')
        for fact in facts:
            if (not isinstance(fact, dict) or fact.get('kind') not in ('semantic', 'episodic', 'state')
                    or not isinstance(fact.get('key'), str) or not 1 <= len(fact['key']) <= 160
                    or not isinstance(fact.get('content'), dict)
                    or not isinstance(fact['content'].get('text'), str) or not 1 <= len(fact['content']['text']) <= 500):
                raise ValueError('invalid_extraction')
            item = MemoryItem.objects.filter(friend=friend, key=fact['key']).first()
            if item and (job.message_id <= max(item.evidence_id, item.blocked_through_id)
                         or (item.manual and not fact.get('corrected'))):
                continue
            if item is None:
                item = MemoryItem(friend=friend, key=fact['key'], kind=fact['kind'])
                action = 'create'
            else:
                if item.content == fact['content'] and item.status == 'active':
                    # Reaffirmation advances evidence order, otherwise an older
                    # contradictory job could overwrite a newer duplicate fact.
                    item.source_message_id, item.evidence_id, item.update_time = job.message_id, job.message_id, now()
                    if item.kind == 'state':
                        item.expires_at = now() + timedelta(days=7)
                    item.save(update_fields=['source_message', 'evidence_id', 'update_time', 'expires_at'])
                    continue
                item.version += 1
                action = 'correct' if fact.get('corrected') else 'update'
            item.kind, item.content, item.status = fact['kind'], fact['content'], 'active'
            item.source_message_id, item.evidence_id = job.message_id, job.message_id
            item.manual, item.confidence, item.update_time = False, 1.0, now()
            if item.kind == 'state':
                item.expires_at = now() + timedelta(days=7)
            item.save()
            _change(item, action, job.message)
        MemoryJob.objects.filter(pk=job_id, lease_token=token).update(status='done', lease_token='', lease_until=None, error_code='', update_time=now())
    return True


def process_job(job_id):
    try:
        token = claim(job_id)
    except OperationalError:
        return False  # A competing SQLite writer leaves the job ready for recovery.
    if not token:
        return False
    try:
        return apply_job(job_id, token)
    except Exception as exc:
        # No content or exception text in durable errors; transient locks can be retried.
        try:
            MemoryJob.objects.filter(pk=job_id, lease_token=token, status='running').update(status='failed',
                error_code=type(exc).__name__[:32], lease_token='', lease_until=None,
                retry_at=now() + timedelta(seconds=5), update_time=now())
        except OperationalError:
            pass  # If failure recording is locked too, the expired lease remains recoverable.
        return False


def invalidate(friend_id, expected_revision, **values):
    changed = Friend.objects.filter(pk=friend_id, memory_revision=expected_revision).update(
        memory_revision=F('memory_revision') + 1, memory_epoch=F('memory_epoch') + 1, update_time=now(), **values)
    if not changed:
        raise MemoryConflict('stale_revision')
    MemoryJob.objects.filter(friend_id=friend_id, status__in=['pending', 'running', 'failed']).update(
        status='cancelled', lease_token='', lease_until=None, update_time=now())


def forget_items(friend):
    floor = Message.objects.filter(friend=friend).order_by('-pk').values_list('pk', flat=True).first() or friend.memory_floor
    for item in MemoryItem.objects.filter(friend=friend):
        item.content, item.status, item.source_message, item.evidence_id = {}, 'deleted', None, 0
        item.blocked_through_id, item.version, item.update_time = max(floor, item.blocked_through_id), item.version + 1, now()
        item.save()
        item.changes.update(content={}, source_message=None)
        _change(item, 'forget', actor='manual')
    return floor


def edit_item(friend, item, text, expected_revision):
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise ValueError('invalid_memory_text')
    with transaction.atomic():
        invalidate(friend.pk, expected_revision, memory_legacy_retired=True)
        item.refresh_from_db()
        item.content = {'text': text.strip()}
        item.manual, item.status, item.version = True, 'active', item.version + 1
        item.confidence = None
        item.update_time = now()
        item.save()
        _change(item, 'manual_edit', actor='manual')


def delete_item(friend, item, expected_revision):
    with transaction.atomic():
        # Retire legacy summary from injection as it may contain the forgotten fact.
        invalidate(friend.pk, expected_revision, memory_legacy_retired=True)
        item.refresh_from_db()
        floor = Message.objects.filter(friend=friend).order_by('-pk').values_list('pk', flat=True).first() or friend.memory_floor
        Friend.objects.filter(pk=friend.pk).update(memory_floor=max(floor, friend.memory_floor))
        item.content, item.status, item.source_message, item.evidence_id = {}, 'deleted', None, 0
        item.blocked_through_id, item.version = max(floor, item.blocked_through_id), item.version + 1
        item.update_time = now()
        item.save()
        item.changes.update(content={}, source_message=None)
        _change(item, 'forget', actor='manual')


def retrieve_memories(friend, query='', k=12):
    if not friend.memory_enabled:
        return []
    eligible = MemoryItem.objects.filter(friend=friend, status='active').filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now()))
    rows = list(eligible.exclude(key='name').order_by('-update_time', '-pk')[:100])
    name = eligible.filter(key='name').first()
    if name:
        rows.append(name)
    def rank(item):
        # Name is always useful; explicit topic overlap favors related stable facts.
        subject = item.content.get('subject', '')
        return (item.key == 'name', bool(subject and subject in query), item.kind == 'state', item.update_time)
    rows.sort(key=rank, reverse=True)
    return [dict(id=f'memory:{r.pk}', text=r.content.get('text', ''), kind=r.kind, version=r.version,
                 source_message_id=r.source_message_id) for r in rows[:k] if r.content.get('text')]
