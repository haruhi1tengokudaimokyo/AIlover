"""Regression checks for adding a game character without replacing existing data."""
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, SimpleTestCase, override_settings
from PIL import Image

from web.documents.utils.story_pipeline import build_bundle, PARSER_VERSION
from web.documents.utils.story_retriever import StoryRetriever
from web.models.character import Character
from web.models.friend import Friend, Message, SystemPrompt
from web.models.user import UserProfile
from web.views.friend.get_or_create import _character_payload


class MugiSeedTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cards = self.root / 'seed_cards'
        cards.mkdir()
        source = Path(settings.BASE_DIR) / 'seed_cards/mugi.json'
        (cards / 'mugi.json').write_bytes(source.read_bytes())
        self.media = self.root / 'media'
        self.stage = self.media / 'character/stage'
        self.stage.mkdir(parents=True)
        # Synthetic pixels for contract testing, never product character assets.
        for name in ('mugi-avatar.webp', 'mugi-background.webp', 'mugi-portrait.webp'):
            Image.new('RGB', (4, 4), 'black').save(self.stage / name)
        self.override = override_settings(BASE_DIR=self.root, MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = User.objects.create_user(username='mugi-owner')
        self.owner = UserProfile.objects.create(user=self.user)
        # A different character with the same display name must not be reused.
        self.original = Character.objects.create(author=self.owner, name='麦', slug='hika', profile='user edited')
        self.friend = Friend.objects.create(me=self.owner, character=self.original, memory='keep memory')
        self.message = Message.objects.create(friend=self.friend, user_message='keep input', output='keep output')

    def seed(self):
        call_command('seed_ousama', slug='mugi', username=self.user.username, stdout=io.StringIO())

    def test_selected_character_is_added_idempotently_without_touching_old_character_or_chat(self):
        with patch.dict(os.environ, {'MUGI_VOICE': 'test-voice-id'}):
            self.seed()
        self.original.refresh_from_db()
        self.assertEqual((self.original.slug, self.original.profile), ('hika', 'user edited'))
        self.assertEqual(Message.objects.get(pk=self.message.pk).output, 'keep output')
        self.friend.refresh_from_db()
        self.assertEqual(self.friend.memory, 'keep memory')
        mugi = Character.objects.get(author=self.owner, slug='mugi')
        self.assertEqual(mugi.voice, 'test-voice-id')
        self.assertTrue(mugi.photo.name.endswith('.webp'))
        mugi.name = 'my edited name'
        mugi.save()
        self.seed()
        self.assertEqual(Character.objects.filter(author=self.owner, slug='mugi').count(), 1)
        mugi.refresh_from_db()
        self.assertEqual(mugi.name, 'my edited name')
        self.assertEqual(mugi.voice, 'test-voice-id')

    def test_missing_original_art_fails_before_database_changes(self):
        (self.stage / 'mugi-avatar.webp').unlink()
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Character.objects.filter(slug='mugi').exists())
        self.assertEqual(SystemPrompt.objects.count(), 0)

    def test_mugi_payload_uses_original_game_assets_and_topics(self):
        self.seed()
        mapping = {'mugi': {'url': '/media/character/stage/mugi-portrait.webp',
                   'photo_url': '/media/character/stage/mugi-avatar.webp',
                   'background_url': '/media/character/stage/mugi-background.webp', 'display_ready': True}}
        with patch('web.views.friend.assets.portrait_map', return_value=mapping):
            payload = _character_payload(Character.objects.get(slug='mugi'))
        self.assertEqual(payload['assets']['portrait_url'], mapping['mugi']['url'])
        self.assertEqual(payload['photo'], mapping['mugi']['photo_url'])
        self.assertEqual(payload['background_image'], mapping['mugi']['background_url'])
        self.assertEqual(len(payload['quick_replies']), 3)
        self.assertTrue(payload['greeting'])


class MugiBundleTests(SimpleTestCase):
    def test_character_filter_excludes_tagged_mugi_scenes_without_changing_other_characters(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'sample.ks').write_text(
                '*H_Start\n[むぎ]\n[>>]料理を作ります。[<<]\n'
                '[緋華]\n[>>]料理はこちら。[<<]\n'
                '*daily\n[むぎ]\n[>>]お帰りなさい。[<<]\n', encoding='utf-8')
            output = root / 'bundle'
            build_bundle(source, output, character_filters={'mugi': lambda row: row.get('label') != 'H_Start'})
            rows = [json.loads(line) for line in (output / 'dialogue_examples.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([(r['character'], r['label']) for r in rows], [('hika', 'H_Start'), ('mugi', 'daily')])
            self.assertEqual(len((output / 'records.jsonl').read_text(encoding='utf-8').splitlines()), 3)

    def test_old_alias_cache_is_reparsed_and_mugi_retrieval_is_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'sample.ks').write_text(
                '*start\n[むぎ vo=vo1_1]\n[>>]料理を作ります。[<<]\n'
                '[緋華]\n[>>]料理はこちら。[<<]\n', encoding='utf-8')
            first = root / 'first'
            build_bundle(source, first)
            cache_file = first / 'parse_cache.jsonl'
            cache = json.loads(cache_file.read_text(encoding='utf-8'))
            cache['parser_version'] = 1
            cache['rows'][0]['character'] = None
            cache_file.write_text(json.dumps(cache, ensure_ascii=False) + '\n', encoding='utf-8')
            second = root / 'second'
            report = build_bundle(source, second, previous=first)
            self.assertGreater(PARSER_VERSION, 1)
            self.assertEqual(report['reused_source_files'], 0)
            hits, _ = StoryRetriever('style', root=second).retrieve('mugi', '料理', strategy='sparse')
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]['character'], 'mugi')
            self.assertEqual(hits[0]['voice_id'], 'vo1_1')
