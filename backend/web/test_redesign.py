import asyncio
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from web.streaming import async_stream
from web.views.friend.assets import portrait_url_for


class StreamingAdapterTests(SimpleTestCase):
    async def test_bridge_yields_incrementally_and_closes_generator(self):
        events = []
        def source():
            try:
                events.append('first')
                yield 'data: first\n\n'
                events.append('second')
                yield 'data: second\n\n'
            finally:
                events.append('closed')
        stream = async_stream(source())
        self.assertEqual(await anext(stream), 'data: first\n\n')
        self.assertEqual(events, ['first'])
        await stream.aclose()
        self.assertEqual(events, ['first', 'closed'])

    async def test_completed_bridge_drains_all_packets(self):
        def source():
            yield 'start'
            yield '[DONE]'
        self.assertEqual([packet async for packet in async_stream(source())], ['start', '[DONE]'])

    def test_uncomposited_atlas_is_not_a_display_portrait(self):
        with patch('web.views.friend.assets.portrait_map', return_value={
                'hika': {'url': '/media/character/portraits/hika.png', 'display_ready': False}}):
            self.assertIsNone(portrait_url_for('hika'))

    def test_windows_path_escape_is_rejected(self):
        with patch('web.views.friend.assets.portrait_map', return_value={'bad': '/media/..\\secret.png'}):
            self.assertIsNone(portrait_url_for('bad'))


class LobbyContractTests(TestCase):
    def test_bad_pagination_has_a_stable_error_code(self):
        response = self.client.get('/api/homepage/index/', {'items_count': -1})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_pagination')

    def test_health_check(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
