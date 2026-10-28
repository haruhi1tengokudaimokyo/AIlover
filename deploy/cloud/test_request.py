"""Manual paid acceptance helper. No requests without explicit --approved-billing.

Environment: RUNPOD_ENDPOINT_ID, RUNPOD_API_KEY, RUNPOD_WORKER_SECRET.
Requires httpx (already installed in the AIlover backend environment).
"""
import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
import uuid
import httpx


async def main(args):
    endpoint = os.environ['RUNPOD_ENDPOINT_ID']
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+', endpoint):
        raise ValueError('Invalid endpoint ID')
    url = 'https://api.runpod.ai/v2/' + endpoint
    headers = {'Authorization': 'Bearer ' + os.environ['RUNPOD_API_KEY']}
    data = {'role': args.role, 'text': '你好，今天过得怎么样？',
            'request_id': uuid.uuid4().hex, 'timestamp': int(time.time())}
    if args.health:
        data['operation'] = 'health'
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    data['signature'] = hmac.new(os.environ['RUNPOD_WORKER_SECRET'].encode(), canonical, hashlib.sha256).hexdigest()
    job, done = None, False
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            async with asyncio.timeout(300):
                response = await client.post(url + '/run', headers=headers, json={'input': data})
                response.raise_for_status()
                candidate = response.json()['id']
                if not re.fullmatch(r'[A-Za-z0-9_-]+', candidate):
                    raise ValueError('Invalid job ID')
                job = candidate
                while True:
                    response = await client.get(url + '/status/' + job, headers=headers)
                    response.raise_for_status()
                    result = response.json()
                    status = result['status']
                    print(status, flush=True)
                    if status == 'COMPLETED':
                        output = result['output']
                        if args.health:
                            print(json.dumps(output))
                        else:
                            assert output['role'] == args.role and output['request_id'] == data['request_id']
                            assert output['mime'] == 'audio/mpeg'
                            audio = base64.b64decode(output['audio_base64'], validate=True)
                            target = Path(args.output)
                            target.write_bytes(audio)
                            print(str(target.resolve()), len(audio), hashlib.sha256(audio).hexdigest())
                        done = True
                        return
                    if status in ('FAILED', 'CANCELLED', 'TIMED_OUT'):
                        raise RuntimeError('Worker job unsuccessful')
                    await asyncio.sleep(2)
        finally:
            if job and not done:
                await client.post(url + '/cancel/' + job, headers=headers)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-billing', action='store_true')
    parser.add_argument('--role', choices=('hika', 'ayame', 'mugi', 'hotaru'), default='mugi')
    parser.add_argument('--health', action='store_true')
    parser.add_argument('--output', default='runtime/cloud/acceptance.mp3')
    args = parser.parse_args()
    if not args.approved_billing:
        parser.error('Cloud acceptance requires deployment credentials and prior billing approval')
    asyncio.run(main(args))
