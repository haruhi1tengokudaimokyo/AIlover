"""One serialized four-role worker. No weights or credentials baked into image."""
import base64
from collections import OrderedDict
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import wave

ROLES = ('hika', 'ayame', 'mugi', 'hotaru')
LOCK = threading.Lock()
CACHE = OrderedDict()
ENGINE = None
CURRENT = None
HEALTH = None


def authenticate(data):
    secret = os.environ.get('WORKER_SHARED_SECRET')
    if not secret:
        raise ValueError('Worker secret not configured')
    if data.get('role') not in ROLES or not isinstance(data.get('text'), str) or not 1 <= len(data['text']) <= 300:
        raise ValueError('Invalid voice request')
    if not isinstance(data.get('request_id'), str) or not 1 <= len(data['request_id']) <= 80:
        raise ValueError('Invalid request identifier')
    if abs(time.time() - int(data.get('timestamp', 0))) > 300:
        raise ValueError('Expired voice request')
    fields = {k: data[k] for k in ('role', 'text', 'request_id', 'timestamp')}
    if 'operation' in data:
        if data['operation'] not in ('health', 'synthesize'):
            raise ValueError('Invalid operation')
        fields['operation'] = data['operation']
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(data.get('signature', ''))):
        raise ValueError('Invalid request signature')
    return hashlib.sha256(canonical).hexdigest()


def handler(job):
    global ENGINE, CURRENT, HEALTH
    data = job.get('input', {})
    fingerprint = authenticate(data)
    with LOCK:
        if data.get('operation') == 'health':
            import torch
            return {**(HEALTH or {}), 'cuda': torch.cuda.is_available(), 'current_role': CURRENT}
        now = time.time()
        for key in list(CACHE):
            if now - CACHE[key][0] > 600:
                del CACHE[key]
        if data['request_id'] in CACHE:
            _, digest, output = CACHE[data['request_id']]
            if digest != fingerprint:
                raise ValueError('Request identifier reused with different input')
            return output
        import torch
        from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config
        root = Path(os.environ.get('MODEL_ROOT', '/runpod-volume/ailover'))
        plan = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        role = data['role']
        selected = plan['characters'][role]
        if not torch.cuda.is_available():
            raise RuntimeError('GPU unavailable')
        if ENGINE is None and torch.cuda.mem_get_info()[0] < 4 * 1024**3:
            raise RuntimeError('Insufficient free GPU memory')
        try:
            if ENGINE is None:
                # Upstream rewrites its config when loading/switching weights.
                # Keep the hashed network-volume config strictly read-only.
                config = TTS_Config(json.loads((root / (role + '-tts.yaml')).read_text(encoding='utf-8')))
                config.configs_path = '/tmp/ailover-current-tts.yaml'
                ENGINE = TTS(config)
                CURRENT = role
            elif CURRENT != role:
                # Invalidate before either mutation, so partial switches cannot leak a voice.
                CURRENT = None
                ENGINE.init_t2s_weights(selected['s1_weights'])
                ENGINE.init_vits_weights(selected['s2_weights'])
                CURRENT = role
            chunks = list(ENGINE.run({'text': data['text'], 'text_lang': 'zh', 'prompt_lang': 'ja',
                'prompt_text': selected['reference_text'], 'ref_audio_path': selected['reference_audio'],
                'text_split_method': 'cut0', 'batch_size': 1, 'seed': 20261028,
                'streaming_mode': False, 'parallel_infer': False}))
            import numpy as np
            if not chunks:
                raise RuntimeError('No audio generated')
            rate = chunks[0][0]
            if any(sr != rate for sr, _ in chunks):
                raise RuntimeError('Inconsistent sample rates')
            samples = np.concatenate([a for _, a in chunks])
            if samples.size > rate * 120:
                raise RuntimeError('Audio too long')
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(samples.astype('<i2').tobytes())
            audio = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0', '-f', 'mp3', 'pipe:1'],
                input=buffer.getvalue(), capture_output=True, check=True, timeout=30).stdout
            output = {'role': role, 'request_id': data['request_id'], 'mime': 'audio/mpeg',
                      'audio_base64': base64.b64encode(audio).decode('ascii')}
            CACHE[data['request_id']] = (now, fingerprint, output)
            while len(CACHE) > 16 or sum(len(v[2]['audio_base64']) for v in CACHE.values()) > 32 * 1024**2:
                CACHE.popitem(last=False)
            return output
        except Exception:
            ENGINE, CURRENT = None, None
            torch.cuda.empty_cache()
            raise RuntimeError('Voice worker failed; model state reset') from None


if __name__ == '__main__':
    import runpod
    from bootstrap import prepare
    HEALTH = prepare(Path(os.environ.get('MODEL_ROOT', '/runpod-volume/ailover')))
    runpod.serverless.start({'handler': handler})
