"""CPU-only HTTP mocks: no platform calls or model loading.

Run: python -m unittest discover -s deploy/cloud/text -p test_gateway.py
Requires FastAPI/Starlette as supplied by the vLLM image.
"""
import asyncio
import json
import os
import unittest
from unittest.mock import patch
import httpx
import gateway


class GatewayTests(unittest.TestCase):
    def test_unauthorized_and_unknown_character(self):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://fixture') as client:
                with patch.dict(os.environ, TEXT_GATEWAY_SECRET='fixture'):
                    response = await client.post('/v1/chat/completions', json={'model': 'ailover-mugi'})
                    self.assertEqual(response.status_code, 401)
                    response = await client.post('/v1/chat/completions', headers={'X-AILOVER-Key': 'fixture'}, json={'model': 'other'})
                    self.assertEqual(response.status_code, 400)
        asyncio.run(run())

    def test_four_roles_and_stream_forwarded_with_internal_key(self):
        async def run():
            calls = []
            def transport(request):
                self.assertEqual(request.headers['Authorization'], 'Bearer internal-key')
                calls.append(json.loads(request.content)['model'])
                return httpx.Response(200, text='data: {"choices":[]}\n\ndata: [DONE]\n\n',
                                      headers={'content-type': 'text/event-stream'})
            factory = httpx.AsyncClient
            async with factory(transport=httpx.ASGITransport(app=gateway.app), base_url='http://fixture') as client:
                with patch.dict(os.environ, TEXT_GATEWAY_SECRET='fixture', VLLM_API_KEY='internal-key'), \
                     patch('gateway.httpx.AsyncClient', side_effect=lambda **kw: factory(transport=httpx.MockTransport(transport), **kw)):
                    for role in ('hika', 'ayame', 'mugi', 'hotaru'):
                        response = await client.post('/v1/chat/completions', headers={'X-AILOVER-Key': 'fixture'},
                                                     json={'model': 'ailover-' + role, 'stream': True, 'messages': []})
                        self.assertEqual(response.status_code, 200)
                        self.assertIn('[DONE]', response.text)
            self.assertEqual(len(set(calls)), 4)
        asyncio.run(run())

    def test_readiness_failure_is_not_healthy(self):
        async def run():
            factory = httpx.AsyncClient
            async with factory(transport=httpx.ASGITransport(app=gateway.app), base_url='http://fixture') as client:
                with patch('gateway.httpx.AsyncClient', side_effect=lambda **kw: factory(
                    transport=httpx.MockTransport(lambda req: httpx.Response(503)), **kw)):
                    self.assertEqual((await client.get('/ping')).status_code, 503)
        asyncio.run(run())
