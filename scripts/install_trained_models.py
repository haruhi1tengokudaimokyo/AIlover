"""Install only deployable weights/references from verified local deliveries."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def unpack(archive, target, select=lambda n: True):
    with ZipFile(archive) as z:
        for item in z.infolist():
            p = PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or ':' in item.filename or '\\' in item.filename:
                raise ValueError('Unsafe model archive')
            if item.is_dir() or not select(item.filename):
                continue
            dest = target.joinpath(*p.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and dest.stat().st_size == item.file_size:
                continue
            with z.open(item) as src, dest.open('wb') as dst:
                import shutil
                shutil.copyfileobj(src, dst)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime')
    args = parser.parse_args()
    source = ROOT / '训练成果/AutoDL_四角色'
    receipt = json.loads((source / '完整回传确认.json').read_text(encoding='utf-8-sig'))
    entries = receipt['artifacts']
    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if entry.get('kind') == 'baseline_text':
            continue
        path = source / Path(entry['local_path']).name
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                raise ValueError('Model digest mismatch: ' + path.name)
        kind = entry['kind']
        unpack(path, target / ('shared' if kind == 'shared_base' else 'characters'),
               (lambda n: '/adapter/' in n or n.endswith('/summary.json')) if kind == 'text' else
               (lambda n: '/references/' in n or '/weights/' in n and ('_e12_' in n or '-e15.ckpt' in n)) if kind == 'voice' else lambda n: True)
        print('INSTALLED', path.name, flush=True)
    source_zip = target / 'shared/GPT-SoVITS-source.zip'
    unpack(source_zip, target / 'source')
    upstream = next((target / 'source').glob('GPT-SoVITS-*'))
    pretrained = target / 'shared/GPT-SoVITS/GPT_SoVITS/pretrained_models'
    # Upstream speaker embedding and Chinese frontend use fixed relative paths.
    # Hard links provide those paths without duplicating gigabytes of weights.
    for original, alias in ((pretrained, upstream / 'GPT_SoVITS/pretrained_models'),
        (target / 'shared/GPT-SoVITS/GPT_SoVITS/text/G2PWModel', upstream / 'GPT_SoVITS/text/G2PWModel')):
        for path in original.rglob('*'):
            if path.is_file():
                dest = alias / path.relative_to(original)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    os.link(path, dest)
    manifest = {'base_model': str(target / 'shared/Qwen2.5-7B-Instruct'), 'characters': {}}
    for index, role in enumerate(('hika', 'ayame', 'mugi', 'hotaru')):
        folder = target / 'characters' / role
        reference = json.loads((folder / 'references/references.json').read_text(encoding='utf-8'))[0]
        s1 = next((folder / 'weights/GPT_v2Pro').glob('*-e15.ckpt'))
        s2 = next((folder / 'weights/SoVITS_v2Pro').glob('*_e12_*.pth'))
        manifest['characters'][role] = {'model': 'ailover-' + role, 'api_base': 'http://127.0.0.1:8001/v1',
            'adapter': str(folder / 'adapter'), 'tts_url': f'http://127.0.0.1:{9891+index}',
            'reference_audio': str(folder / 'references' / Path(reference['audio_path']).name),
            'reference_text': reference['ja_text'], 's1_weights': str(s1), 's2_weights': str(s2)}
        cfg = {'custom': {'device': 'cuda', 'is_half': True, 'version': 'v2Pro',
            't2s_weights_path': str(s1), 'vits_weights_path': str(s2),
            'bert_base_path': str(pretrained / 'chinese-roberta-wwm-ext-large'),
            'cnhuhbert_base_path': str(pretrained / 'chinese-hubert-base')}}
        (target / (role + '-tts.yaml')).write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    manifest['speech_source'] = str(upstream)
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('MANIFEST', target / 'manifest.json', flush=True)


if __name__ == '__main__':
    main()
