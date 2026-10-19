import json
import os
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from web.models.user import UserProfile
from web.models.character import Character
from web.models.friend import Friend, Message, MemoryItem, MemoryJob
from web.documents.utils import debug_trace
from web.documents.utils.evaluation_store import isolated_store
from web.views.friend.message.memory.structured import delete_item


class EvaluationIsolationTests(TestCase):
    def test_disposable_database_routes_reads_writes_and_restores_default_on_failure(self):
        alias = 'evaluation_isolation_fixture'
        before = User.objects.count()
        with patch.object(type(self), 'databases', type(self).databases | {alias}), patch('web.documents.utils.evaluation_store.uuid.uuid4', return_value=SimpleNamespace(hex='isolation_fixture')):
            with self.assertRaises(RuntimeError):
                with isolated_store() as created:
                    self.assertEqual(created, alias)
                    User.objects.create_user(username='never-in-application-db')
                    path = Path(connections[created].settings_dict['NAME'])
                    self.assertEqual(User.objects.count(), 1)
                    raise RuntimeError('synthetic failure')
        self.assertFalse(path.exists())
        self.assertNotIn(alias, connections.databases)
        self.assertEqual(User.objects.count(), before)

    def test_offline_ablation_real_memory_checks_and_no_application_rows(self):
        alias = 'evaluation_offline_fixture'
        before = (User.objects.count(), Friend.objects.count(), Message.objects.count(), MemoryItem.objects.count())
        with tempfile.TemporaryDirectory() as directory, patch.object(type(self), 'databases', type(self).databases | {alias}), patch('web.documents.utils.evaluation_store.uuid.uuid4', return_value=SimpleNamespace(hex='offline_fixture')), patch('web.management.commands.evaluate_roleplay.ChatGraph.create_app', side_effect=AssertionError('API forbidden')):
            target = Path(directory) / 'report.json'
            call_command('evaluate_roleplay', offline=True, include_extended=True, variant='all', case='structured_correction', history_pairs=0, output=str(target), stdout=StringIO())
            report = json.loads(target.read_text(encoding='utf-8'))
        self.assertTrue(report['isolated_database_deleted'])
        self.assertEqual(len(report['cases']), 4)
        memory = next(case for case in report['cases'] if case['variant'] == 'story_memory')
        self.assertTrue(all(value for turn in memory['turns'] for value in turn['memory_state_checks'].values()))
        self.assertTrue(memory['turns'][-1]['trace']['context']['injected_ids']['memory'])
        self.assertEqual((User.objects.count(), Friend.objects.count(), Message.objects.count(), MemoryItem.objects.count()), before)

    def test_real_retrieval_requires_explicit_api_opt_in_and_strict_dense_no_fallback(self):
        with self.assertRaises(CommandError), patch('web.management.commands.evaluate_retrieval.dense_search', side_effect=AssertionError):
            call_command('evaluate_retrieval', dense_provider='real', stdout=StringIO())
        from web.documents.utils.retrieval_evaluation import evaluate
        data = json.loads((Path(__file__).resolve().parents[1] / 'evaluation/retrieval_synthetic.json').read_text(encoding='utf-8'))
        report = evaluate(data, dense=lambda *args: [], dense_label='disabled')
        self.assertEqual(report['strategies']['dense']['aggregate']['recall_at_k'], 0)
        self.assertEqual(report['strategies']['sparse']['aggregate']['recall_at_k'], 1)

    def test_human_scores_are_explicit_and_mock_reports_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            report, scores, output = [Path(directory) / name for name in ('report.json', 'scores.json', 'scored.json')]
            report.write_text(json.dumps({'offline':True,'cases':[]}), encoding='utf-8')
            scores.write_text(json.dumps({'scores':[]}), encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('score_roleplay', report=str(report), scores=str(scores), output=str(output), stdout=StringIO())
            report.write_text(json.dumps({'offline':False,'cases':[{'id':'fixture','variant':'story','human_score':None,'human_dimensions':{'role_consistency':None}}]}), encoding='utf-8')
            scores.write_text(json.dumps({'scores':[{'id':'fixture','variant':'story','dimensions':{'role_consistency':3}}]}), encoding='utf-8')
            call_command('score_roleplay', report=str(report), scores=str(scores), output=str(output), stdout=StringIO())
            graded = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(graded['human_aggregate']['story']['role_consistency'], {'mean':3,'n':1})


@override_settings(DEBUG=True)
class DebugPermissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='synthetic-debug-owner')
        profile = UserProfile.objects.create(user=self.user)
        character = Character.objects.create(author=profile, name='synthetic', profile='fixture', slug='synthetic')
        self.friend = Friend.objects.create(me=profile, character=character)
        self.source = Message.objects.create(friend=self.friend, user_message='合成用户来源', input='never-expose-private-prompt', output='fixture')
        self.item = MemoryItem.objects.create(friend=self.friend, key='name', kind='semantic', content={'text':'合成记忆'}, source_message=self.source)
        self.ident = str(uuid.uuid4())
        self.trace = {'context': {'injected_ids': {'memory':[f'memory:{self.item.pk}'], 'lore':['synthetic-kitchen'], 'style':[]},
                                  'memory_versions': {f'memory:{self.item.pk}':1}}, 'retrieval':[]}
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.flags = patch.dict(os.environ, {'ROLEPLAY_DEBUG_TRACE':'true'})
        self.flags.start(); self.addCleanup(self.flags.stop)
        debug_trace.save(self.friend.pk, self.ident, self.trace)

    def get(self, **params):
        return self.client.get('/api/friend/message/chat/debug/', {'friend_id':self.friend.pk, 'generation_id':self.ident, **params})

    def test_default_disabled_production_and_expired_trace_return404(self):
        with patch.dict(os.environ, {'ROLEPLAY_DEBUG_TRACE':'false'}):
            self.assertEqual(self.get().status_code, 404)
        with override_settings(DEBUG=False):
            self.assertEqual(self.get().status_code, 404)
        instant = debug_trace.time.monotonic()
        with patch('web.documents.utils.debug_trace.time.monotonic', return_value=instant + 901):
            self.assertEqual(self.get().status_code, 404)

    def test_sources_private_no_internal_prompt_and_wrong_generation_denied(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['evidence']['memory'][0]['source']['user_message'], '合成用户来源')
        self.assertNotIn('never-expose-private-prompt', json.dumps(response.data))
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(self.get(generation_id=str(uuid.uuid4())).status_code, 404)
        self.client.force_authenticate(User.objects.create_user(username='synthetic-debug-intruder'))
        self.assertEqual(self.get().status_code, 404)

    def test_forgotten_memory_does_not_leak_from_old_trace(self):
        delete_item(self.friend, self.item, self.friend.memory_revision)
        self.assertEqual(self.get().data['evidence']['memory'], [])

    def test_original_evidence_bound_to_character_and_injected_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [dict(id='synthetic-kitchen', character='synthetic', text='合成证据', source_file='synthetic.ks'),
                    dict(id='not-injected', character='synthetic', text='不能暴露的未注入内容'),
                    dict(id='other-character', character='other', text='其他角色资料')]
            Path(directory, 'story_knowledge.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
            with patch.dict(os.environ, {'STORY_DATA_DIR':directory}):
                response = self.get()
            self.assertEqual([row['id'] for row in response.data['evidence']['lore']], ['synthetic-kitchen'])
