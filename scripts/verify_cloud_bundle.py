"""Offline checksum, manifest and deployment source validation; never calls a cloud API."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('hika', 'ayame', 'mugi', 'hotaru')


def verify(folder):
    inventory = json.loads((folder / 'SHA256.json').read_text(encoding='utf-8'))
    total = 0
    for name, item in inventory.items():
        path = (folder / name).resolve()
        assert path.is_relative_to(folder.resolve()), 'Unsafe inventory member'
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        assert actual == (item['sha256'] if isinstance(item, dict) else item), 'SHA mismatch: ' + name
        size = path.stat().st_size
        if isinstance(item, dict):
            assert size == item['bytes'], 'Size mismatch: ' + name
        total += size
    return {'files': len(inventory), 'bytes': total, 'sha256_verified': True}


def main():
    result = {'oss': {}, 'tts': {}, 'static': {}}
    cloud = ROOT / 'runtime/cloud'
    audit = json.loads((cloud / 'compatibility.json').read_text(encoding='utf-8'))
    for role in ROLES:
        folder = cloud / 'oss' / role
        assert {p.name for p in folder.iterdir()} == {'adapter_config.json', 'adapter_model.safetensors', 'config.json', 'SHA256.json'}
        cfg = json.loads((folder / 'adapter_config.json').read_text())
        assert cfg['r'] == 32 and cfg['lora_alpha'] == 64
        assert audit[role]['local_import_candidate'] and not audit[role]['platform_import_validated']
        result['oss'][role] = verify(folder)
    folder = cloud / 'runpod-tts'
    result['tts'] = verify(folder)
    plan = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    assert set(plan['characters']) == set(ROLES)
    for role, entry in plan['characters'].items():
        assert re.search(r'[\u3040-\u30ff]', entry['reference_text']), 'Missing Japanese reference text'
        for field in ('s1_weights', 's2_weights', 'reference_audio'):
            relative = entry[field].removeprefix('/runpod-volume/ailover/')
            assert relative.startswith(role + '/') and (folder / relative).is_file(), 'Invalid role mapping'
        cfg = json.loads((folder / (role + '-tts.yaml')).read_text())['custom']
        assert cfg['version'] == 'v2Pro' and cfg['device'] == 'cuda'
    for name in ('text', 'tts'):
        source = ROOT / 'deploy/cloud' / name
        docker = (source / 'Dockerfile').read_text()
        assert ':latest' not in docker
        for line in docker.splitlines():
            if line.startswith('COPY '):
                assert (source / line.split()[1]).is_file(), 'Missing Docker COPY source'
        for file in source.glob('*.py'):
            ast.parse(file.read_text(encoding='utf-8'), filename=str(file))
        result['static'][name] = {'docker_copy_sources': True, 'python_syntax': True,
                                  'image_built': False, 'gpu_inference_tested': False}
    (cloud / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
