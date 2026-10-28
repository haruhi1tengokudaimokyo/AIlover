"""Single-GPU OpenAI-compatible SSE server with serialized character adapters."""
import argparse
import asyncio
import json
from pathlib import Path
import threading
import time
import uuid


def main():
    import torch
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import StreamingResponse
    from peft import PeftModel
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, TextIteratorStreamer, StoppingCriteria, StoppingCriteriaList
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if not torch.cuda.is_available():
        raise RuntimeError('This runtime requires a CUDA GPU; no silent CPU fallback')
    tokenizer = AutoTokenizer.from_pretrained(manifest['base_model'], local_files_only=True)
    base = AutoModelForCausalLM.from_pretrained(manifest['base_model'], local_files_only=True,
        device_map={'': 0}, torch_dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
            bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16))
    roles = manifest['characters']
    first = next(iter(roles))
    model = PeftModel.from_pretrained(base, roles[first]['adapter'], adapter_name=first)
    for role, route in roles.items():
        if role != first:
            model.load_adapter(route['adapter'], adapter_name=role)
    model.eval()
    app, gate = FastAPI(), asyncio.Semaphore(1)

    @app.get('/v1/models')
    async def models():
        return {'object': 'list', 'data': [{'id': r['model'], 'object': 'model'} for r in roles.values()]}

    @app.post('/v1/chat/completions')
    async def chat(body: dict):
        role = next((r for r, v in roles.items() if v['model'] == body.get('model')), None)
        messages = body.get('messages')
        if role is None or not isinstance(messages, list) or not messages or len(messages) > 100:
            raise HTTPException(400, 'Invalid character model or messages')
        if any(m.get('role') not in ('system', 'user', 'assistant') or not isinstance(m.get('content'), str) for m in messages):
            raise HTTPException(400, 'Only text conversation messages are supported')
        tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors='pt')
        if tokens.shape[1] > 12000:
            raise HTTPException(400, 'Conversation context is too long')
        limit = max(1, min(1000, int(body.get('max_tokens', 400))))
        temperature = max(.01, min(1.5, float(body.get('temperature', .8))))
        async def output():
            async with gate:
                model.set_adapter(role)
                stop = threading.Event()
                errors = []
                class Cancel(StoppingCriteria):
                    def __call__(self, input_ids, scores, **kwargs):
                        return stop.is_set()
                streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
                def generate():
                    try:
                        with torch.inference_mode():
                            model.generate(tokens.to('cuda'), streamer=streamer, max_new_tokens=limit,
                                do_sample=True, temperature=temperature, top_p=.9, repetition_penalty=1.08,
                                stopping_criteria=StoppingCriteriaList([Cancel()]), pad_token_id=tokenizer.eos_token_id)
                    except Exception as exc:
                        errors.append(exc)
                        streamer.end()
                worker = threading.Thread(target=generate, daemon=True)
                worker.start()
                ident = 'chatcmpl-' + uuid.uuid4().hex
                def next_chunk():
                    return next(streamer, None)
                try:
                    while True:
                        chunk = await asyncio.to_thread(next_chunk)
                        if chunk is None:
                            break
                        event = {'id': ident, 'object': 'chat.completion.chunk', 'created': int(time.time()),
                            'model': body['model'], 'choices': [{'index': 0, 'delta': {'content': chunk}, 'finish_reason': None}]}
                        yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
                    if errors:
                        raise RuntimeError('Model generation failed') from errors[0]
                    yield 'data: ' + json.dumps({'id': ident, 'object': 'chat.completion.chunk',
                        'model': body['model'], 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}) + '\n\n'
                    yield 'data: [DONE]\n\n'
                finally:
                    stop.set()
                    # Never switch adapters while a cancelled generation still runs.
                    while worker.is_alive():
                        try:
                            await asyncio.shield(asyncio.to_thread(worker.join, .1))
                        except asyncio.CancelledError:
                            stop.set()
        return StreamingResponse(output(), media_type='text/event-stream')
    uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
