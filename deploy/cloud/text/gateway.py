"""RunPod HTTP gateway: readiness plus a separate application secret.

RunPod's edge authenticates Authorization with RUNPOD_API_KEY. The second
X-AILOVER-Key header is checked here, before forwarding to internal vLLM.
"""
import hmac
import json
import os
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

app = FastAPI()


@app.get('/ping')
async def ping():
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get('http://127.0.0.1:8001/health')
            response.raise_for_status()
        return {'status': 'healthy'}
    except httpx.HTTPError:
        raise HTTPException(503, 'Model loading or unavailable') from None


@app.post('/v1/chat/completions')
async def completions(request: Request):
    expected = os.environ.get('TEXT_GATEWAY_SECRET', '')
    provided = request.headers.get('X-AILOVER-Key', '')
    if not expected or not hmac.compare_digest(expected.encode(), provided.encode()):
        raise HTTPException(401, 'Invalid application credential')
    raw = await request.body()
    if len(raw) > 1024**2:
        raise HTTPException(413, 'Request too large')
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'Invalid JSON') from None
    if not isinstance(payload, dict):
        raise HTTPException(400, 'Expected a JSON object')
    if payload.get('model') not in {f'ailover-{r}' for r in ('hika', 'ayame', 'mugi', 'hotaru')}:
        raise HTTPException(400, 'Unknown character model')
    client = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5), trust_env=False)
    try:
        upstream = await client.send(client.build_request('POST', 'http://127.0.0.1:8001/v1/chat/completions',
            json=payload, headers={'Authorization': 'Bearer ' + os.environ['VLLM_API_KEY']}), stream=True)
    except Exception:
        await client.aclose()
        raise HTTPException(503, 'Text model unavailable') from None
    if upstream.status_code != 200:
        await upstream.aclose()
        await client.aclose()
        return Response(status_code=upstream.status_code, content='Text model rejected request')

    async def close():
        await upstream.aclose()
        await client.aclose()

    async def stream():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await close()
    return StreamingResponse(stream(), media_type=upstream.headers.get('content-type', 'text/event-stream'),
                             background=BackgroundTask(close))
