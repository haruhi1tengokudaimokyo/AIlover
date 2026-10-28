"""Hotaru installs independently and reuses the real multi-character chat path."""
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from langchain_core.messages import HumanMessage
from PIL import Image

from web.models.character import Character
from web.models.friend import Friend, Message
from web.models.user import UserProfile
from web.views.friend.get_or_create import _character_payload
from web.views.friend.message.chat.chat import add_system_prompt


class HotaruIntegrationTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cards = self.root / 'seed_cards'
        cards.mkdir()
        # Synthetic card for software contracts, never installed as product lore.
        (cards / 'hotaru.json').write_text(json.dumps(dict(slug='hotaru', name='水无月萤',
            profile='软件契约测试角色卡', greeting='测试开场白', quick_replies=['测试话题'],
            voice_env='HOTARU_VOICE', voice_default='longanyang'), ensure_ascii=False), encoding='utf-8')
        self.stage = self.root / 'media/character/stage'
        self.stage.mkdir(parents=True)
        for name in ('portrait', 'avatar', 'background'):
            Image.new('RGB', (4, 4), 'black').save(self.stage / f'hotaru-{name}.webp')
        self.override = override_settings(BASE_DIR=self.root, MEDIA_ROOT=self.root / 'media')
        self.override.enable()
        self.addCleanup(self.override.disable)
        user = User.objects.create_user(username='hotaru-contract-owner')
        self.owner = UserProfile.objects.create(user=user)
        self.old = Character.objects.create(author=self.owner, name='水无月萤', slug='hika', profile='keep profile')
        self.friend = Friend.objects.create(me=self.owner, character=self.old, memory='keep memory')
        self.message = Message.objects.create(friend=self.friend, user_message='keep input', input='keep prompt', output='keep output')

    def seed(self):
        call_command('seed_amatsutsumi', username=self.owner.user.username, stdout=io.StringIO())

    def test_separate_seed_preserves_old_character_and_memory_even_with_same_display_name(self):
        with patch.dict(os.environ, {'HOTARU_VOICE': 'test-hotaru-service-id'}):
            self.seed()
        hotaru = Character.objects.get(slug='hotaru')
        self.assertEqual(hotaru.voice, 'test-hotaru-service-id')
        self.assertTrue(hotaru.photo.name.endswith('.webp'))
        hotaru.name = 'edited display name'
        hotaru.save()
        self.seed()
        self.assertEqual(Character.objects.filter(slug='hotaru').count(), 1)
        self.old.refresh_from_db()
        self.friend.refresh_from_db()
        self.assertEqual((self.old.slug, self.old.profile, self.friend.memory), ('hika', 'keep profile', 'keep memory'))
        self.assertEqual(Message.objects.get(pk=self.message.pk).output, 'keep output')

    def test_missing_original_art_fails_without_any_role_creation(self):
        (self.stage / 'hotaru-avatar.webp').unlink()
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Character.objects.filter(slug='hotaru').exists())

    def test_ousama_default_does_not_install_cross_game_card(self):
        with self.assertRaises(CommandError):
            call_command('seed_ousama', username=self.owner.user.username, stdout=io.StringIO())
        self.assertFalse(Character.objects.filter(slug='hotaru').exists())

    def test_payload_and_actual_context_retrieve_only_hotaru_and_preserve_identity_mode(self):
        self.seed()
        hotaru = Character.objects.get(slug='hotaru')
        mapping = {'hotaru': dict(url='/media/character/stage/hotaru-portrait.webp',
            photo_url='/media/character/stage/hotaru-avatar.webp',
            background_url='/media/character/stage/hotaru-background.webp', display_ready=True)}
        with patch('web.views.friend.assets.portrait_map', return_value=mapping):
            payload = _character_payload(hotaru)
        self.assertEqual(payload['assets']['portrait_url'], mapping['hotaru']['url'])
        self.assertEqual(payload['photo'], mapping['hotaru']['photo_url'])
        story = self.root / 'story'
        story.mkdir()
        rows = [dict(id='synthetic-hotaru', text='做饭之前先休息一下，今天真的有点累。', character='hotaru',
                     source_file='test.ps3', source_location={'byte_offset': 12}, context=[]),
                dict(id='synthetic-other', text='做饭之前先休息一下。', character='hika', source_file='test.ks')]
        (story / 'dialogue_examples.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
        (story / 'story_knowledge.jsonl').write_text('', encoding='utf-8')
        friend = SimpleNamespace(character=hotaru, memory='', memory_enabled=False)
        for identity in ('real_user', 'protagonist'):
            with patch.dict(os.environ, {'STORY_DATA_DIR': str(story), 'ROLEPLAY_RAG_MODE': 'story',
                'STORY_RETRIEVAL_STRATEGY': 'sparse', 'STORY_DENSE_ENABLED': 'false', 'ROLEPLAY_IDENTITY_MODE': identity}):
                result = add_system_prompt({'messages': [HumanMessage('做饭前先休息吧')]}, friend, '做饭前先休息吧')
            self.assertEqual(result['trace']['context']['identity'], identity)
            self.assertEqual(result['trace']['context']['injected_ids']['style'], ['synthetic-hotaru'])
            self.assertNotIn('synthetic-other', str(result['messages']))
            self.assertIn('中文汉化译文', result['messages'][0].content)
