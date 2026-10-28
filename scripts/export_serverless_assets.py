"""Minimal TTS network-volume tree, pinned dependencies and upload inventory."""
import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
runtime = ROOT / 'runtime'
out = runtime / 'cloud/runpod-tts'
out.mkdir(parents=True, exist_ok=True)
manifest = json.loads((runtime / 'manifest.json').read_text(encoding='utf-8'))
plan = {'characters': {}}


def link(src, relative):
    dst = out / relative
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        os.link(src, dst)
    elif not os.path.samefile(src, dst):
        with src.open('rb') as original, dst.open('rb') as exported:
            if hashlib.file_digest(original, 'sha256').digest() != hashlib.file_digest(exported, 'sha256').digest():
                raise ValueError('Refusing to overwrite differing exported asset: ' + str(dst))
    return '/runpod-volume/ailover/' + Path(relative).as_posix()


for role, route in manifest['characters'].items():
    plan['characters'][role] = {}
    for field in ('s1_weights', 's2_weights', 'reference_audio'):
        src = Path(route[field])
        plan['characters'][role][field] = link(src, role + '/' + src.name)
    plan['characters'][role]['reference_text'] = route['reference_text']
    common = '/runpod-volume/ailover/common/'
    cfg = {'custom': {'device': 'cuda', 'is_half': True, 'version': 'v2Pro',
        't2s_weights_path': plan['characters'][role]['s1_weights'],
        'vits_weights_path': plan['characters'][role]['s2_weights'],
        'bert_base_path': common + 'chinese-roberta-wwm-ext-large',
        'cnhuhbert_base_path': common + 'chinese-hubert-base'}}
    (out / (role + '-tts.yaml')).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
for name in ('chinese-roberta-wwm-ext-large', 'chinese-hubert-base', 'sv'):
    folder = runtime / 'shared/GPT-SoVITS/GPT_SoVITS/pretrained_models' / name
    for src in folder.rglob('*'):
        if src.is_file():
            link(src, 'common/' + name + '/' + src.relative_to(folder).as_posix())
folder = runtime / 'shared/GPT-SoVITS/GPT_SoVITS/text/G2PWModel'
for src in folder.rglob('*'):
    if src.is_file():
        link(src, 'G2PWModel/' + src.relative_to(folder).as_posix())
for src in (runtime / 'shared/dictionaries').iterdir():
    link(src, 'dictionaries/' + src.name)
(out / 'manifest.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
inventory = {}
for src in out.rglob('*'):
    if src.is_file() and src.name != 'SHA256.json':
        with src.open('rb') as f:
            inventory[src.relative_to(out).as_posix()] = {'bytes': src.stat().st_size, 'sha256': hashlib.file_digest(f, 'sha256').hexdigest()}
(out / 'SHA256.json').write_text(json.dumps(inventory, indent=2))
# Preserve the real Linux training environment as an additional constraint file.
archive = next((ROOT / '训练成果/AutoDL_四角色').glob('AIlover_mugi_Voice*.zip'))
with ZipFile(archive) as z:
    freeze = z.read('training_code/speech-environment.txt').decode()
    portable = [line for line in freeze.splitlines() if '==' in line and '@' not in line]
    excluded = [line.split(' @ ')[0] for line in freeze.splitlines() if '@' in line or line.startswith('-e')]
    (ROOT / 'deploy/cloud/tts/training-environment.lock.txt').write_text('\n'.join(portable) + '\n', encoding='utf-8')
    (ROOT / 'deploy/cloud/tts/nonportable-packages.json').write_text(json.dumps(excluded, indent=2), encoding='utf-8')
print(json.dumps({'files': len(inventory), 'bytes': sum(v['bytes'] for v in inventory.values()), 'output': str(out)}))
