"""RunPod load-balancing HTTP endpoint; VLLM_API_KEY is injected as a secret."""
import os
import subprocess
import signal
import uvicorn
from gateway import app

if not os.environ.get('VLLM_API_KEY'):
    raise RuntimeError('VLLM_API_KEY must be configured')
if not os.environ.get('TEXT_GATEWAY_SECRET'):
    raise RuntimeError('TEXT_GATEWAY_SECRET must be configured')
root = os.getenv('TEXT_MODEL_ROOT', '/runpod-volume/ailover-text')
args = ['vllm', 'serve', root + '/base', '--host', '127.0.0.1', '--port', '8001',
        '--served-model-name', 'ailover-base', '--enable-lora', '--max-lora-rank', '32',
        '--max-loras', '4', '--max-cpu-loras', '4', '--max-model-len', '4096',
        '--gpu-memory-utilization', '0.85', '--lora-modules']
args += [f'ailover-{r}={root}/lora/{r}' for r in ('hika', 'ayame', 'mugi', 'hotaru')]
child = subprocess.Popen(args)
try:
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
finally:
    child.send_signal(signal.SIGTERM)
    try:
        child.wait(timeout=15)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
