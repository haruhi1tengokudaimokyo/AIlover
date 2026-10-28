#!/usr/bin/env bash
set -euo pipefail
ROOT=/root/autodl-tmp/ailover
mkdir -p "$ROOT"/{incoming,logs,models,outputs,reports,envs,cache}
export TMPDIR="$ROOT/cache"
export PIP_CACHE_DIR="$ROOT/cache/pip"
export HF_HOME="$ROOT/cache/huggingface"
export MODELSCOPE_CACHE="$ROOT/cache/modelscope"
trap 'echo "BOOTSTRAP_FAILED line=$LINENO exit=$?"' ERR
date -u
/root/miniconda3/bin/python -m venv --system-site-packages "$ROOT/envs/text"
PY="$ROOT/envs/text/bin/python"
"$PY" -m pip install --disable-pip-version-check \
  transformers==4.51.3 peft==0.15.2 accelerate==1.6.0 \
  bitsandbytes==0.45.5 huggingface-hub==0.30.2 modelscope==1.25.0
"$PY" -m pip freeze > "$ROOT/reports/text-environment.txt"
"$PY" - <<'PY'
from pathlib import Path
import json,sys,torch
from modelscope import snapshot_download
root=Path('/root/autodl-tmp/ailover')
assert torch.cuda.is_available(), 'CUDA unavailable in text environment'
print('GPU_READY',torch.cuda.get_device_name(0),torch.__version__,flush=True)
model=root/'models/Qwen2.5-7B-Instruct'
snapshot_download('Qwen/Qwen2.5-7B-Instruct',local_dir=str(model))
assert (model/'config.json').is_file(), 'Base-model download incomplete'
(root/'reports/bootstrap-ready.json').write_text(json.dumps({'status':'ready','model':str(model),'torch':torch.__version__,'python':sys.version},indent=2))
print('BOOTSTRAP_READY',flush=True)
PY
