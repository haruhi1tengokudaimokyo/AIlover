import asyncio
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import AsyncMock, patch, Mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.core.management import call_command
from langchain_core.messages import AIMessageChunk, AIMessage, HumanMessage, ToolMessage
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from web.models.user import UserProfile
from web.models.character import Character
from web.models.friend import Friend, Message
from web.views.friend.message.chat.chat import MessageChatView, add_system_prompt, add_recent_messages
from web.views.friend.message.asr.asr import ASRView
from web.views.friend.message.memory.update import update_memory
from web.documents.utils import style_retriever


class FakeModel:
    def __init__(self, fail=False):
        self.fail = fail

    async def astream(self, inputs, **kwargs):
        yield AIMessageChunk(content='你好，'), {}
        if self.fail:
            raise RuntimeError('fake provider failure')
        yield ToolMessage(content='内部工具结果', tool_call_id='test'), {}
        yield AIMessageChunk(content='今天过得怎么样？', usage_metadata={
            'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15,
        }), {}


class ChatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='testing123')
        self.profile = UserProfile.objects.create(user=self.user)
        self.character = Character.objects.create(author=self.profile, name='绯华', profile='嘴硬心软', greeting='你来啦。')
        self.friend = Friend.objects.create(me=self.profile, character=self.character)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.inputs = {'messages': [HumanMessage('你好')]}

    def events(self, app, audio=False):
        return list(MessageChatView().event_stream(app, self.inputs, self.friend, '你好', audio))

    def test_text_mode_saves_before_done_and_excludes_tools(self):
        with patch.object(MessageChatView, 'stream_voice', new_callable=AsyncMock) as voice:
            stream = MessageChatView().event_stream(FakeModel(), self.inputs, self.friend, '你好', False)
            for packet in stream:
                if '[DONE]' in packet:
                    self.assertEqual(Message.objects.count(), 1)
            voice.assert_not_called()
        saved = Message.objects.get()
        self.assertEqual(saved.output, '你好，今天过得怎么样？')
        self.assertEqual(saved.total_tokens, 15)

    def test_voice_failure_preserves_text(self):
        with patch.object(MessageChatView, 'stream_voice', new=AsyncMock(side_effect=RuntimeError('no voice'))), self.assertLogs(level='WARNING'):
            packets = self.events(FakeModel(), audio=True)
        self.assertTrue(any('warning' in item for item in packets))
        self.assertEqual(Message.objects.get().output, '你好，今天过得怎么样？')

    def test_model_failure_does_not_save_partial_reply(self):
        with self.assertLogs(level='ERROR'):
            packets = self.events(FakeModel(fail=True))
        self.assertTrue(any('error' in item for item in packets))
        self.assertEqual(Message.objects.count(), 0)

    def test_invalid_inputs_return_400(self):
        for payload in [{}, {'friend_id': self.friend.pk, 'message': []},
                        {'friend_id': 'bad', 'message': '你好'},
                        {'friend_id': self.friend.pk, 'message': '长' * 2001},
                        {'friend_id': self.friend.pk, 'message': '你好', 'audio': 'false'}]:
            self.assertEqual(self.client.post('/api/friend/message/chat/', payload, format='json').status_code, 400)

    def test_missing_key_returns_actionable_error(self):
        with patch.dict(os.environ, {'API_KEY': ''}):
            response = self.client.post('/api/friend/message/chat/', {'friend_id': self.friend.pk, 'message': '你好'}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertIn('API_KEY', response.data['result'])

    def test_cannot_chat_with_other_users_friend(self):
        other = User.objects.create_user(username='other')
        self.client.force_authenticate(other)
        response = self.client.post('/api/friend/message/chat/', {'friend_id': self.friend.pk, 'message': '你好'}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_greeting_and_history_are_context(self):
        state = add_system_prompt(self.inputs, self.friend, '你好')
        fresh = add_recent_messages(state, self.friend)['messages']
        self.assertEqual(fresh[1].content, '你来啦。')
        Message.objects.create(friend=self.friend, user_message='叫我小明', input='', output='知道啦。')
        context = add_recent_messages(state, self.friend)['messages']
        self.assertEqual([m.content for m in context[1:]], ['叫我小明', '知道啦。', '你好'])
        self.assertIn('绯华', context[0].content)

    def test_memory_update_no_longer_crashes(self):
        app = Mock()
        app.invoke.return_value = {'messages': [AIMessage('用户叫小明。')]}
        with patch('web.views.friend.message.memory.update.MemoryGraph.create_app', return_value=app):
            update_memory(self.friend)
        self.friend.refresh_from_db()
        self.assertEqual(self.friend.memory, '用户叫小明。')

    def test_stale_memory_cannot_overwrite_new_summary(self):
        Friend.objects.filter(pk=self.friend.pk).update(memory='用户叫小红。')
        app = Mock()
        app.invoke.return_value = {'messages': [AIMessage('用户叫小明。')]}
        with patch('web.views.friend.message.memory.update.MemoryGraph.create_app', return_value=app):
            update_memory(self.friend)
        self.friend.refresh_from_db()
        self.assertEqual(self.friend.memory, '用户叫小红。')

    def test_refresh_ignores_expired_access_header(self):
        client = APIClient()
        client.cookies['refresh_token'] = str(RefreshToken.for_user(self.user))
        client.credentials(HTTP_AUTHORIZATION='Bearer expired-token')
        response = client.post('/api/user/account/refresh_token/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['access'])

    def test_memory_can_be_edited_and_old_revision_rejected(self):
        endpoint = '/api/friend/memory/'
        response = self.client.patch(endpoint, {'friend_id': self.friend.pk, 'memory': '用户叫小林。', 'enabled': False, 'revision': 0}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['revision'], 1)
        stale = self.client.patch(endpoint, {'friend_id': self.friend.pk, 'memory': '旧数据', 'enabled': True, 'revision': 0}, format='json')
        self.assertEqual(stale.status_code, 409)
        self.friend.refresh_from_db()
        self.assertEqual(self.friend.memory, '用户叫小林。')
        self.assertFalse(self.friend.memory_enabled)

    def test_disabled_memory_makes_no_model_request(self):
        self.friend.memory_enabled = False
        with patch('web.views.friend.message.memory.update.MemoryGraph.create_app') as model:
            update_memory(self.friend)
        model.assert_not_called()

    def test_manual_clear_prevents_inflight_summary_restore(self):
        app = Mock()
        def delayed_result(inputs):
            self.client.patch('/api/friend/memory/', {'friend_id': self.friend.pk, 'memory': '', 'enabled': False, 'revision': 0}, format='json')
            return {'messages': [AIMessage('旧摘要') ]}
        app.invoke.side_effect = delayed_result
        with patch('web.views.friend.message.memory.update.MemoryGraph.create_app', return_value=app):
            update_memory(self.friend)
        self.friend.refresh_from_db()
        self.assertEqual(self.friend.memory, '')

    def test_history_search_and_export_are_private_and_omit_prompts(self):
        Message.objects.create(friend=self.friend, user_message='今天吃蛋包饭', input='private system prompt', output='我来做。')
        response = self.client.get('/api/friend/message/search/', {'friend_id': self.friend.pk, 'q': '蛋包饭'})
        self.assertEqual(len(response.data['messages']), 1)
        exported = self.client.get('/api/friend/message/export/', {'friend_id': self.friend.pk})
        data = json.loads(b''.join(exported.streaming_content))
        exported.close()
        self.assertEqual(data['messages'][0]['user_message'], '今天吃蛋包饭')
        self.assertNotIn('input', data['messages'][0])
        other = User.objects.create_user(username='other-history')
        self.client.force_authenticate(other)
        for endpoint in ['/api/friend/memory/', '/api/friend/message/search/', '/api/friend/message/export/']:
            self.assertEqual(self.client.get(endpoint, {'friend_id': self.friend.pk, 'q': '蛋包饭'}).status_code, 404)

    def test_clear_history_requires_confirmation_and_disables_memory(self):
        Message.objects.create(friend=self.friend, user_message='秘密', input='', output='嗯。')
        endpoint = '/api/friend/message/clear/'
        self.assertEqual(self.client.delete(endpoint, {'friend_id': self.friend.pk}, format='json').status_code, 400)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(self.client.delete(endpoint, {'friend_id': self.friend.pk, 'confirm': 'CLEAR'}, format='json').status_code, 200)
        self.assertEqual(Message.objects.count(), 0)
        self.friend.refresh_from_db()
        self.assertFalse(self.friend.memory_enabled)
        self.assertEqual(self.friend.memory_revision, 1)

    def test_active_chat_blocks_another_request_and_clear(self):
        from web.views.friend.message.leases import acquire
        lease = acquire(self.friend.pk)
        try:
            with patch.dict(os.environ, {'API_KEY': 'test-key'}):
                response = self.client.post('/api/friend/message/chat/', {'friend_id': self.friend.pk, 'message': '你好'}, format='json')
            self.assertEqual(response.status_code, 409)
            response = self.client.delete('/api/friend/message/clear/', {'friend_id': self.friend.pk, 'confirm': 'CLEAR'}, format='json')
            self.assertEqual(response.status_code, 409)
        finally:
            lease.release()
        next_lease = acquire(self.friend.pk)
        self.assertIsNotNone(next_lease)
        lease.release()  # 双重关闭不能释放下一个请求的锁。
        self.assertIsNone(acquire(self.friend.pk))
        next_lease.release()

    def test_response_close_releases_lease_before_stream_starts(self):
        from web.views.friend.message.leases import acquire
        with patch.dict(os.environ, {'API_KEY': 'test-key'}), patch('web.views.friend.message.chat.chat.ChatGraph.create_app', return_value=FakeModel()):
            response = self.client.post('/api/friend/message/chat/', {'friend_id': self.friend.pk, 'message': '你好'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(acquire(self.friend.pk))
        response.close()
        lease = acquire(self.friend.pk)
        self.assertIsNotNone(lease)
        lease.release()

    def test_runtime_status_does_not_expose_keys_or_url_credentials(self):
        with patch.dict(os.environ, {'API_KEY': 'secret-do-not-print', 'API_BASE': 'https://user:password@example.com/v1?key=hidden'}):
            response = self.client.get('/api/settings/status/')
        self.assertEqual(response.data['model_host'], 'example.com')
        self.assertNotIn('secret-do-not-print', str(response.data))
        self.assertNotIn('password', str(response.data))
        self.assertNotIn('hidden', str(response.data))

    def test_friend_list_uses_friend_id_not_character_id(self):
        extra_character = Character.objects.create(author=self.profile, name='占位角色', profile='测试')
        extra_character.delete()
        third = Character.objects.create(author=self.profile, name='另一角色', profile='测试')
        friend = Friend.objects.create(me=self.profile, character=third)
        self.assertNotEqual(friend.pk, third.pk)
        response = self.client.get('/api/friend/get_list/')
        self.assertEqual(response.data['friends'][0]['id'], friend.pk)

    def test_character_editor_preserves_profile_and_updates_voice(self):
        response = self.client.post('/api/create/character/update/', {
            'character_id': self.character.pk, 'name': '绯华', 'profile': '新的角色设定，不是名字',
            'voice': 'custom-voice', 'greeting': '欢迎回来。', 'quick_replies': json.dumps(['今天吃什么？']),
        }, format='json')
        self.assertEqual(response.data['result'], 'success')
        self.character.refresh_from_db()
        self.assertEqual(self.character.profile, '新的角色设定，不是名字')
        self.assertEqual(self.character.voice, 'custom-voice')
        self.assertEqual(self.character.greeting, '欢迎回来。')

    def test_character_editor_rejects_invalid_quick_topics(self):
        response = self.client.post('/api/create/character/update/', {'character_id': self.character.pk,
            'name': '绯华', 'profile': '角色设定', 'quick_replies': '{}'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_history_validates_cursor_and_requires_owner(self):
        self.assertEqual(self.client.get('/api/friend/message/get_history/', {'friend_id': self.friend.pk, 'last_message_id': '-1'}).status_code, 400)
        self.assertEqual(self.client.get('/api/friend/message/get_history/', {'friend_id': self.friend.pk}).status_code, 200)
        self.client.force_authenticate(User.objects.create_user(username='not-owner'))
        self.assertEqual(self.client.get('/api/friend/message/get_history/', {'friend_id': self.friend.pk}).status_code, 404)


class RetrievalTests(TestCase):
    def setUp(self):
        # The public review package must run without copyrighted game assets.
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        rows = [{'text': f'合成資料です。台所で料理とご飯を用意します。番号{i}。', 'file': f'food-{i}.ks'} for i in range(6)]
        rows += [{'text': '合成資料です。仕事で疲れたので今夜は早く休みます。', 'file': 'rest.ks'}]
        for slug in ('hika', 'ayame'):
            (root / f'{slug}.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
        patcher = patch.object(style_retriever, '_lines_path', side_effect=lambda slug: root / f'{slug}.jsonl')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(style_retriever._load_samples.cache_clear)

    def test_without_index_uses_local_synthetic_style_samples(self):
        with patch.object(style_retriever, 'table_exists', return_value=False):
            lines = style_retriever.retrieve('hika', '今天吃什么？')
        self.assertEqual(len(lines), 5)
        self.assertEqual(len(set(lines)), 5)

    def test_embedding_failure_does_not_block_chat(self):
        with patch.object(style_retriever, '_retrieve_vector', side_effect=RuntimeError('embedding unavailable')), self.assertLogs(level='WARNING'):
            lines = style_retriever.retrieve('ayame', '今天吃什么料理？')
            self.assertTrue(lines)
            self.assertTrue(any(word in lines[0] for word in ['料理', '食', 'ご飯', 'お腹', '台所']))

    def test_invalid_slug_cannot_read_outside_corpus(self):
        self.assertEqual(style_retriever.retrieve('../../settings', '你好'), [])

    def test_build_passes_embedding_argument(self):
        with patch('lancedb.connect'), patch('langchain_community.vectorstores.LanceDB.from_documents') as build, patch('web.documents.utils.custom_embeddings.CustomEmbeddings'):
            build.return_value._table.count_rows.return_value = 7
            self.assertEqual(style_retriever.build_index('hika'), 7)
        self.assertIn('embedding', build.call_args.kwargs)
        self.assertEqual(len(build.call_args.kwargs['documents']), 7)

    def test_local_topic_ranking_is_repeatable_and_varies_by_query(self):
        with patch.object(style_retriever, 'table_exists', return_value=False):
            food = style_retriever.retrieve('hika', '我饿了，做饭吧')
            self.assertEqual(food, style_retriever.retrieve('hika', '我饿了，做饭吧'))
            self.assertNotEqual(food, style_retriever.retrieve('hika', '今天工作好累'))
        self.assertTrue(any(word in food[0] for word in ['料理', '食', 'ご飯', 'お腹', '台所']))

    def test_evaluation_defaults_to_offline(self):
        from io import StringIO
        output = StringIO()
        with patch('web.views.friend.message.chat.graph.ChatGraph.create_app') as model:
            call_command('evaluate_roleplay', stdout=output)
        model.assert_not_called()
        self.assertIn('12', output.getvalue())

    def test_backup_uses_snapshot_and_excludes_env(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.sqlite3'
            connection = sqlite3.connect(source)
            connection.execute('create table example (value text)')
            connection.execute("insert into example values ('saved')")
            connection.commit()
            connection.close()
            media = root / 'media'
            media.mkdir()
            (media / 'photo.txt').write_text('photo')
            (media / '.env').write_text('API_KEY=secret')
            from types import SimpleNamespace
            config = SimpleNamespace(DATABASES={'default': {'NAME': source}}, MEDIA_ROOT=media, DATA_DIR=root)
            with patch('web.management.commands.backup_data.settings', config):
                call_command('backup_data', output_dir=str(root / 'backups'), verbosity=0)
            archive_path = next((root / 'backups').glob('*.zip'))
            with ZipFile(archive_path) as archive:
                self.assertIn('db.sqlite3', archive.namelist())
                self.assertIn('media/photo.txt', archive.namelist())
                self.assertNotIn('media/.env', archive.namelist())
                copied = root / 'copied.sqlite3'
                copied.write_bytes(archive.read('db.sqlite3'))
            connection = sqlite3.connect(copied)
            try:
                self.assertEqual(connection.execute('select value from example').fetchone()[0], 'saved')
            finally:
                connection.close()


class SpeechTests(TestCase):
    def test_asr_collects_all_sentences_before_finish(self):
        class Socket:
            def __aiter__(self):
                async def packets():
                    for text in ['你好。', '我回来了。']:
                        yield json.dumps({'header': {'event': 'result-generated'}, 'payload': {'output': {
                            'transcription': {'sentence_end': True, 'text': text}}}})
                    yield json.dumps({'header': {'event': 'task-finished'}})
                return packets()
        self.assertEqual(asyncio.run(ASRView().asr_receiver(Socket())), '你好。我回来了。')
