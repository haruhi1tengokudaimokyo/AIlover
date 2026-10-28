"""Remove proven generated duplicates; keep central deliveries and build inputs.

No game archives, native extracted audio, application data, or legacy frozen
datasets are deletion targets. ZIP aliases use atomic NTFS hard-link replacement.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
CENTER = ROOT / '训练材料'
AUDIT = CENTER / '清理记录.json'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def bounded(path, allowed):
    path = Path(path)
    resolved = path.resolve()
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        raise ValueError('Refusing linked cleanup target')
    if not any(resolved.is_relative_to(base.resolve()) and resolved != base.resolve() for base in allowed):
        raise ValueError('Cleanup target outside named generated-data directories: ' + str(path))
    if resolved.is_relative_to(CENTER.resolve()):
        raise ValueError('Central materials are protected')
    return resolved


def tree_matches(folder, expected):
    files = [p for p in folder.rglob('*') if p.is_file()]
    if {p.relative_to(folder).as_posix() for p in files} != set(expected):
        return False
    for p in folder.rglob('*'):
        if p.is_symlink() or getattr(p, 'is_junction', lambda: False)():
            return False
    return all(p.stat().st_size == expected[p.relative_to(folder).as_posix()]['bytes']
               and sha(p) == expected[p.relative_to(folder).as_posix()]['sha256'] for p in files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    inventory = json.loads((CENTER / '文件清单_SHA256.json').read_text(encoding='utf-8'))
    zip_by_hash, packages, wavs = {}, {}, {}
    for relative, meta in inventory['files'].items():
        path = CENTER / relative
        if path.stat().st_size != meta['bytes'] or sha(path) != meta['sha256']:
            raise ValueError('Retained central material is incomplete: ' + relative)
        if path.suffix.lower() != '.zip':
            continue
        zip_by_hash[meta['sha256']] = path
        with ZipFile(path) as archive:
            candidates = [n for n in archive.namelist() if n.endswith('/manifest.json')]
            if not candidates:
                continue
            name = min(candidates, key=len)
            prefix = name[:-len('manifest.json')]
            body = archive.read(name)
            expected = json.loads(body)['files']
            expected = {n: {'bytes': m['bytes'], 'sha256': m['sha256']} for n, m in expected.items()}
            expected['manifest.json'] = {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
            packages[path.stem] = (path, expected)
            for member, m in expected.items():
                if member.endswith('.wav'):
                    wavs[m['sha256']] = {'archive': str(path.relative_to(ROOT)), 'member': prefix + member, 'bytes': m['bytes']}
    print('All 153 retained central materials verified.', flush=True)
    allowed = [ROOT / 'finetune_data', ROOT / 'share/training-handoff']
    trees = []
    scan_bases = [ROOT / 'finetune_data/text_v3', ROOT / 'finetune_data/hotaru/preparation-v1',
                  ROOT / 'finetune_data/tts_preparation_v1/20261023/package_builds']
    for base in scan_bases:
        for folder in sorted(base.rglob('AIlover_*')):
            if not folder.is_dir() or folder.name not in packages:
                continue
            bounded(folder, allowed)
            archive, expected = packages[folder.name]
            if tree_matches(folder, expected):
                trees.append({'path': str(folder.relative_to(ROOT)), 'retained_zip': str(archive.relative_to(ROOT)),
                              'files': len(expected), 'bytes': sum(m['bytes'] for m in expected.values())})
    zip_links = []
    zip_paths = list(ROOT.glob('AIlover_*.zip')) + list((ROOT / 'finetune_data').rglob('*.zip')) + list((ROOT / 'share/training-handoff').rglob('*.zip'))
    for path in sorted(zip_paths):
        if any(path.is_relative_to(ROOT / item['path']) for item in trees):
            continue
        if path.parent != ROOT:
            bounded(path, allowed)
        digest = sha(path)
        retained = zip_by_hash.get(digest)
        if retained and not os.path.samefile(path, retained):
            zip_links.append({'path': str(path.relative_to(ROOT)), 'retained_file': str(retained.relative_to(ROOT)),
                              'sha256': digest, 'bytes': path.stat().st_size})
    loose = []
    for base in (ROOT / 'share/training-handoff', ROOT / 'finetune_data/hotaru/preparation-v1/audio_cache'):
        for path in sorted(base.rglob('*.wav')):
            bounded(path, allowed)
            digest = sha(path)
            if digest in wavs and path.stat().st_size == wavs[digest]['bytes']:
                loose.append({'path': str(path.relative_to(ROOT)), 'sha256': digest, **wavs[digest]})
    plan = {'scope': 'verified generated duplicates only', 'central_files_verified': len(inventory['files']),
            'unpacked_copies': trees, 'immutable_zip_aliases': zip_links, 'redundant_generated_wavs': loose,
            'estimated_reclaimed_bytes': sum(r['bytes'] for r in trees + zip_links + loose),
            'original_games_native_audio_database_and_frozen_datasets_preserved': True, 'applied': False}
    AUDIT.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'unpacked_copies': len(trees), 'zip_copies': len(zip_links), 'generated_wav_copies': len(loose),
                      'estimated_reclaimed_bytes': plan['estimated_reclaimed_bytes']}, ensure_ascii=False), flush=True)
    if not args.apply:
        return
    for item in zip_links:
        path, retained = ROOT / item['path'], ROOT / item['retained_file']
        if path.parent != ROOT:
            bounded(path, allowed)
        if sha(path) != item['sha256'] or sha(retained) != item['sha256']:
            raise ValueError('ZIP changed after audit')
        temp = path.with_name(path.name + '.dedup-link')
        os.link(retained, temp)
        os.replace(temp, path)
        if not os.path.samefile(path, retained):
            raise ValueError('ZIP hard-link verification failed')
    for item in trees:
        folder = bounded(ROOT / item['path'], allowed)
        _, expected = packages[folder.name]
        if not tree_matches(folder, expected):
            raise ValueError('Unpacked copy changed after audit')
        shutil.rmtree(folder)
    for item in loose:
        path = bounded(ROOT / item['path'], allowed)
        if sha(path) != item['sha256']:
            raise ValueError('Generated WAV changed after audit')
        path.unlink()
    for relative, meta in inventory['files'].items():
        if sha(CENTER / relative) != meta['sha256']:
            raise ValueError('Retained material changed during cleanup')
    plan['applied'] = True
    plan['retained_materials_reverified_after_cleanup'] = True
    AUDIT.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    with (CENTER / '00_先看这里.md').open('a', encoding='utf-8') as stream:
        stream.write('\n## 重复文件清理后\n\n已删除与保留ZIP内容完全相同的生成目录和旧音频副本。必要的旧ZIP路径使用同盘硬链接，保持脚本兼容，不再重复占用整份空间。原始游戏、原生声音、应用数据库及旧冻结数据集保留。需要解压训练时，直接解压本目录对应角色ZIP。详情见清理记录.json。\n')
    print('Cleanup complete; retained materials reverified.', flush=True)


if __name__ == '__main__':
    main()
