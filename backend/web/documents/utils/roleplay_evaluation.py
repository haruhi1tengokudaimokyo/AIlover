"""Conversation ablations with actual memory in a separate SQLite store."""
import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
from django.conf import settings
from django.core.management.base import CommandError
from django.contrib.auth.models import User
from django.db import connections
from langchain_core.messages import AIMessage, HumanMessage
from web.models.user import UserProfile
from web.models.character import Character
from web.models.friend import Friend, Message, MemoryItem
from web.documents.utils.evaluation_store import isolated_store
from web.documents.utils.story_retriever import read_channel, fingerprint
from web.views.friend.message.chat.chat import add_system_prompt
from web.views.friend.message.memory.structured import enqueue, process_job, delete_item


class OfflineModel:
    def invoke(self, inputs, **kwargs):
        return {'messages': [AIMessage('合成回复，仅验证评测流水线。')]}


def validate_cases(cases):
    if (not isinstance(cases, list) or not cases or any(not isinstance(case, dict) for case in cases)
            or len({case.get('id') for case in cases}) != len(cases)
            or any(not isinstance(case.get('id'), str) or not isinstance(case.get('messages'), list)
                   or not case['messages'] or any(not isinstance(text, str) or not 1 <= len(text) <= 2000 for text in case['messages'])
                   or not isinstance(case.get('review'), str) or not case['review'] for case in cases)):
        raise CommandError('评估用例格式不正确')


def run_evaluation(command, options, graph):
    root = Path(settings.BASE_DIR) / 'evaluation'
    cases = json.loads((root / 'roleplay_cases.json').read_text(encoding='utf-8'))['cases']
    if options['include_extended']:
        cases += json.loads((root / 'roleplay_extended_cases.json').read_text(encoding='utf-8'))['cases']
    validate_cases(cases)
    if not 0 <= options['history_pairs'] <= 10:
        raise CommandError('history-pairs must be 0..10')
    if options['case']:
        cases = [case for case in cases if case['id'] == options['case']]
        if not cases:
            raise CommandError('没有这个用例')
    if not options['run'] and not options['offline']:
        command.stdout.write(f'已验证 {len(cases)} 个评估用例；未调用模型。显式加 --run 才生成真实回复。')
        return
    if options['run'] and not os.getenv('API_KEY', '').strip():
        raise CommandError('尚未配置 API_KEY')
    output = Path(options['output']) if options['output'] else Path(settings.DATA_DIR) / 'evaluations' / f'{options["slug"]}-{time.time_ns()}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open('x', encoding='utf-8') as handle:
            handle.write('{}')
    except FileExistsError:
        raise CommandError('报告文件已存在，请使用新的输出路径') from None
    variants = ['baseline', 'legacy', 'story', 'story_memory'] if options['variant'] == 'all' else [options['variant']]
    card = ({'name': '合成评测角色', 'profile': '仅用于软件契约测试，不是原作人物。', 'slug': 'synthetic'}
            if options['offline'] else json.loads((Path(settings.BASE_DIR) / 'seed_cards' / f'{options["slug"]}.json').read_text(encoding='utf-8')))
    report = {'version': 2, 'requested_slug': options['slug'], 'actual_character': card['slug'],
              'model': 'offline_placeholder_not_role_quality' if options['offline'] else os.getenv('MODEL', 'deepseek-v3.2'),
              'offline': options['offline'], 'requires_human_review': True,
              'memory_implementation': 'actual_structured_memory_in_isolated_sqlite',
              'input_fingerprint': hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
              'history_pairs': options['history_pairs'], 'isolated_database_deleted': False,
              'model_parameters': {key: os.getenv(key, default) for key, default in (
                  ('LLM_TEMPERATURE', '0.95'), ('LLM_TOP_P', '0.9'), ('LLM_FREQUENCY_PENALTY', '0.4'), ('LLM_PRESENCE_PENALTY', '0.3'))}, 'cases': []}
    def save():
        partial = output.with_name(output.name + '.partial-' + uuid.uuid4().hex)
        partial.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        # Windows indexers can briefly hold a just-written report. Retry the
        # same owned artifact, never truncate a previously existing user file.
        for attempt in range(6):
            try:
                partial.replace(output)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.05 * (attempt + 1))
    app = OfflineModel() if options['offline'] else graph.create_app()
    try:
        with isolated_store() as alias:
            fixture_rows = []
            if options['offline']:
                fixture_rows = json.loads((root / 'conversation_evidence_synthetic.json').read_text(encoding='utf-8'))['records']
                fixture_dir = Path(connections[alias].settings_dict['NAME']).parent / 'evidence'
                fixture_dir.mkdir()
                for channel, name in (('lore', 'story_knowledge'), ('style', 'dialogue_examples')):
                    (fixture_dir / f'{name}.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n'
                        for row in fixture_rows if row['evidence_type'] == channel), encoding='utf-8')
                report['corpus_fingerprint'] = fingerprint(fixture_rows)
                report['evidence_is_synthetic'] = True
            else:
                report['corpus_fingerprint'] = fingerprint(list(read_channel('lore')) + list(read_channel('style')))
                report['evidence_is_synthetic'] = False
            profile = UserProfile.objects.create(user=User.objects.create_user(username='isolated-evaluation'))
            character = Character.objects.create(author=profile, name=card['name'], profile=card['profile'], slug=card['slug'])
            for variant in variants:
                for case in cases:
                    friend = Friend.objects.create(me=profile, character=character, memory_enabled=variant == 'story_memory')
                    turns = []
                    mode = {'baseline': 'off', 'legacy': 'legacy', 'story': 'story', 'story_memory': 'story'}[variant]
                    identity = options['identity_mode'] or case.get('identity_mode', 'real_user')
                    for index, text in enumerate(case['messages']):
                        action = case.get('actions_before_turn', {}).get(str(index), {})
                        if variant == 'story_memory' and action.get('forget_key'):
                            item = MemoryItem.objects.filter(friend=friend, key=action['forget_key'], status='active').first()
                            if item:
                                delete_item(friend, item, friend.memory_revision)
                                friend.refresh_from_db()
                        rows = list(Message.objects.filter(friend=friend, pk__gt=friend.memory_floor)
                                    .exclude(memoryjob__error_code='request_epoch_changed').order_by('-pk')[:options['history_pairs']])
                        history = [message for row in reversed(rows) for message in (HumanMessage(row.user_message), AIMessage(row.output))]
                        config = {'ROLEPLAY_RAG_MODE': mode, 'MEMORY_MODE': 'structured', 'ROLEPLAY_IDENTITY_MODE': identity}
                        if options['offline']:
                            config['STORY_DENSE_ENABLED'] = 'false'
                            config['STORY_DATA_DIR'] = str(fixture_dir)
                            config['STORY_RETRIEVAL_STRATEGY'] = 'sparse'
                        # Explicit legacy surrogate deliberately fills unrelated
                        # synthetic examples, without touching a real embedding API.
                        legacy = (patch('web.documents.utils.style_retriever.retrieve',
                                        side_effect=lambda slug, query, k=5: [r['text'] for r in fixture_rows if r['evidence_type'] == 'style'][:k])
                                  if options['offline'] else nullcontext())
                        with patch.dict(os.environ, config), legacy:
                            inputs = add_system_prompt({'messages': history + [HumanMessage(text)]}, friend, text)
                        started = time.monotonic()
                        try:
                            reply = app.invoke({'messages': inputs['messages']}, config={'recursion_limit': 12})['messages'][-1].content
                            if not isinstance(reply, str) or not reply.strip():
                                raise ValueError('invalid_model_reply')
                            message = Message.objects.create(friend=friend, user_message=text, output=reply[:5000], input='')
                            if variant == 'story_memory':
                                job = enqueue(message)
                                if job and not process_job(job.pk):
                                    raise ValueError('memory_job_not_completed')
                            friend.refresh_from_db()
                            active = {item.key: item.content.get('value') for item in MemoryItem.objects.filter(friend=friend, status='active')}
                            expected = case.get('memory_expected_after', {}).get(str(index))
                            checks = ({key: (key not in active if value == '__absent__' else active.get(key) == value)
                                       for key, value in expected.items()} if expected is not None and variant == 'story_memory' else None)
                            turns.append({'user': text, 'reply': reply, 'seconds': round(time.monotonic() - started, 3),
                                          'trace': inputs.get('trace', {}), 'memory_state_checks': checks,
                                          'objective_reply_checks': {f'avoids:{word}': word not in reply for word in case.get('forbidden_reply_fragments', [])}})
                        except Exception as exc:
                            turns.append({'user': text, 'error_type': type(exc).__name__})
                            break
                    report['cases'].append({'id': case['id'], 'variant': variant, 'identity_mode': identity,
                                            'review': case['review'], 'turns': turns, 'human_score': None,
                                            'human_dimensions': {key: None for key in ('role_consistency', 'lore_accuracy',
                                                'unsupported_claims', 'chinese_naturalness', 'multi_turn', 'repetition', 'identity_boundary', 'memory_correction')}})
                    save()
                    command.stdout.write(f'完成用例：{case["id"]} / {variant}')
        report['isolated_database_deleted'] = True
    finally:
        try:
            asyncio.run(graph.close_app(app))
            report['model_client_closed'] = True
        except Exception:
            report['model_client_closed'] = False
        save()
    command.stdout.write(f'报告：{output}；相似度需人工评审，Mock 回复不能评价角色效果。')
