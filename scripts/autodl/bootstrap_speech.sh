#!/usr/bin/env bash
set -euo pipefail
ROOT=/root/autodl-tmp/ailover
SOURCE="$ROOT/code/upstream/GPT-SoVITS-b4570b876f5c086819ba84e3215472733c6a7b70"
export TMPDIR="$ROOT/cache"
export PIP_CACHE_DIR="$ROOT/cache/pip"
export HF_HOME="$ROOT/cache/huggingface-speech"
export MODELSCOPE_CACHE="$ROOT/cache/modelscope-speech"
export PATH="$ROOT/envs/speech/bin:$PATH"
trap 'echo "SPEECH_PREPARATION_FAILED line=$LINENO exit=$?"' ERR
/root/miniconda3/bin/python -m venv --system-site-packages "$ROOT/envs/speech"
PY="$ROOT/envs/speech/bin/python"
cat > "$ROOT/code/speech-constraints.txt" <<'EOF'
torch==2.5.1
torchaudio==2.5.1
numpy==1.26.4
transformers==4.51.3
peft==0.15.2
pytorch-lightning==2.5.1
EOF
# Keep known-working CUDA Torch. Packages install into this separate venv only.
"$PY" -m pip install --disable-pip-version-check --index-url https://pypi.org/simple \
  --timeout 120 --retries 5 -c "$ROOT/code/speech-constraints.txt" \
  -r "$SOURCE/requirements.txt" imageio-ffmpeg
"$PY" -m pip freeze > "$ROOT/reports/speech-environment.txt"
"$PY" - <<'PY'
import json,torch,torchaudio,imageio_ffmpeg,os
from pathlib import Path
root=Path('/root/autodl-tmp/ailover')
assert torch.cuda.is_available()
target=root/'envs/speech/bin/ffmpeg'
if not target.exists():
    target.symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
(root/'reports/speech-environment-ready.json').write_text(json.dumps({
    'torch':torch.__version__,'torchaudio':torchaudio.__version__,
    'gpu':torch.cuda.get_device_name(0),'ffmpeg':str(target)},indent=2))
PY
"$PY" -u "$ROOT/code/prepare_speech.py"
"$PY" -u "$ROOT/code/download_speech_assets.py"
echo SPEECH_PREPARATION_READY
