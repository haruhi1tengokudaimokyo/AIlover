"""Restore the four local Qwen shards from the preserved verified training ZIP.

Not needed for Bailian API chat. No downloads or model training.
"""
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    receipt = json.loads((ROOT / '训练成果/AutoDL_四角色/完整回传确认.json').read_text(encoding='utf-8-sig'))
    entry = next(item for item in receipt['artifacts'] if item['kind'] == 'shared_base')
    archive = ROOT / '训练成果/AutoDL_四角色' / Path(entry['local_path']).name
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
            raise ValueError('Preserved archive checksum mismatch')
    audit = json.loads((ROOT / 'docs/CLOUD_MODEL_COMPATIBILITY.json').read_text(encoding='utf-8'))
    hashes = audit['roles']['hika']['base_files']
    with ZipFile(archive) as z:
        for number in range(1, 5):
            name = f'model-{number:05d}-of-00004.safetensors'
            target = ROOT / 'runtime/shared/Qwen2.5-7B-Instruct' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                with target.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != hashes[name]:
                        raise ValueError('Refusing to overwrite a differing local shard')
                continue
            temporary = target.with_suffix('.restore.tmp')
            try:
                with z.open('Qwen2.5-7B-Instruct/' + name) as source, temporary.open('wb') as output:
                    shutil.copyfileobj(source, output, length=4 * 1024**2)
                with temporary.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != hashes[name]:
                        raise ValueError('Restored shard checksum mismatch')
                temporary.rename(target)
                print('RESTORED', name, flush=True)
            finally:
                if temporary.exists():
                    temporary.unlink()


if __name__ == '__main__':
    main()
