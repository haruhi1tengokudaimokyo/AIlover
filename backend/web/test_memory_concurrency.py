from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.contrib.auth.models import User
from django.db import connections, OperationalError
from django.test import TransactionTestCase
from web.models.user import UserProfile
from web.models.character import Character
from web.models.friend import Friend, Message, MemoryItem, MemoryJob
from web.views.friend.message.memory.structured import enqueue, claim, apply_job, extract_explicit, MemoryConflict


class MemoryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        profile = UserProfile.objects.create(user=User.objects.create_user(username='synthetic-concurrency'))
        character = Character.objects.create(author=profile, name='synthetic', profile='fixture')
        self.friend = Friend.objects.create(me=profile, character=character)

    def job(self, text):
        return enqueue(Message.objects.create(friend=self.friend, user_message=text, input='', output='fixture'))

    def test_competing_workers_have_only_one_lease_owner(self):
        job, barrier = self.job('叫我小明'), Barrier(2)
        def worker():
            try:
                barrier.wait(timeout=5)
                return claim(job.pk)
            except OperationalError:
                return None  # SQLite lock contention is safe; command can recover.
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            tokens = [f.result(timeout=10) for f in futures]
        owners = [token for token in tokens if token]
        self.assertEqual(len(owners), 1)
        self.assertTrue(apply_job(job.pk, owners[0]))
        self.assertEqual(MemoryItem.objects.count(), 1)

    def test_competing_fact_updates_recover_without_lost_correction(self):
        older, newer = self.job('我喜欢咖啡'), self.job('我现在不喝咖啡了')
        tokens = [(older.pk, claim(older.pk)), (newer.pk, claim(newer.pk))]
        barrier = Barrier(2)
        def worker(pair):
            def extract(text):
                barrier.wait(timeout=5)
                return extract_explicit(text)
            try:
                return apply_job(*pair, extractor=extract)
            except (OperationalError, MemoryConflict):
                return False
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(worker, tokens))
        for ident, token in tokens:
            if MemoryJob.objects.get(pk=ident).status == 'running':
                self.assertTrue(apply_job(ident, token))
        self.assertEqual(MemoryItem.objects.count(), 1)
        self.assertFalse(MemoryItem.objects.get().content['value'])
        self.assertEqual(MemoryJob.objects.filter(status='done').count(), 2)
