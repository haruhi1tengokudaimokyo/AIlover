"""Explicit live smoke test for the four user-supplied Bailian model IDs.

Requires --live (sends small billable requests). Never prints credentials.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    'hika': 'qwen2.5-7b-instruct-974feb886208',
    'ayame': 'qwen2.5-7b-instruct-8420bd41b30b',
    'hotaru': 'qwen2.5-7b-instruct-475355645709',
    'mugi': 'qwen2.5-7b-instruct-6f0c05ddbbd4',
}


async def main():
    load_dotenv(ROOT / 'backend/.env')
    key = os.environ['DASHSCOPE_API_KEY']
    results = {}
    async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
        for role, model in MODELS.items():
            started = time.monotonic()
            record = {'model': model, 'success': False}
            try:
                response = await client.post('https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation',
                    headers={'Authorization': 'Bearer ' + key}, json={
                        'model': model, 'input': {'messages': [{'role': 'user', 'content': '请只用一句中文打招呼，30字以内。'}]},
                        'parameters': {'result_format': 'message', 'max_tokens': 64}})
                record['http_status'] = response.status_code
                data = response.json()
                record['request_id'] = data.get('request_id')
                if response.is_success and data.get('output', {}).get('choices'):
                    record.update(success=True, text=data['output']['choices'][0]['message']['content'], usage=data.get('usage'))
                else:
                    record['error_code'] = data.get('code', 'UnknownAPIError')
                    record['error_message'] = str(data.get('message', ''))[:800].replace(key, '[REDACTED]')
            except (httpx.HTTPError, ValueError) as exc:
                record['error_type'] = type(exc).__name__
            record['seconds'] = round(time.monotonic() - started, 2)
            results[role] = record
            print(json.dumps({role: record}, ensure_ascii=False), flush=True)
    target = ROOT / 'runtime/cloud/dashscope-live-results.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.error('Pass --live only with authorization for billable API calls')
    asyncio.run(main())
