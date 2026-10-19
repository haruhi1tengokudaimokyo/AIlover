from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MemoryMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_legacy_rows(self):
        # Django test database only; never run this against a user database.
        executor = MigrationExecutor(connection)
        executor.migrate([('web', '0010_friend_memory_controls')])
        try:
            state = executor.loader.project_state([('web', '0010_friend_memory_controls')]).apps
            User = state.get_model('auth', 'User')
            Profile = state.get_model('web', 'UserProfile')
            Character = state.get_model('web', 'Character')
            Friend = state.get_model('web', 'Friend')
            Message = state.get_model('web', 'Message')
            user = User.objects.create(username='synthetic-migration-owner')
            profile = Profile.objects.create(user=user)
            character = Character.objects.create(author=profile, name='synthetic', profile='fixture')
            friend = Friend.objects.create(me=profile, character=character, memory='保留的合成摘要', memory_revision=7)
            message = Message.objects.create(friend=friend, user_message='synthetic input', input='fixture', output='synthetic output')
            executor = MigrationExecutor(connection)
            executor.migrate([('web', '0011_structured_memory')])
            from web.models.friend import Friend as NewFriend, Message as NewMessage, MemoryItem, MemoryJob
            restored = NewFriend.objects.get(pk=friend.pk)
            self.assertEqual(restored.memory, '保留的合成摘要')
            self.assertEqual(restored.memory_revision, 7)
            self.assertEqual(restored.memory_epoch, 0)
            self.assertFalse(restored.memory_legacy_retired)
            self.assertEqual(NewMessage.objects.get(pk=message.pk).output, 'synthetic output')
            self.assertEqual(MemoryItem.objects.count(), 0)
            self.assertEqual(MemoryJob.objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate([('web', '0011_structured_memory')])
