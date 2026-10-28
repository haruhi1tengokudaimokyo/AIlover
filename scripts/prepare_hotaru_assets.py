"""Extract Hotaru's real CMVS stand/background assets; never generate artwork.

Requires official GARbro 1.5.44 portable DLLs in extracted/amatsutsumi/tools/GARbro.
The read-only C# adapter is compiled locally against .NET Framework/WPF.
Run: .venv/Scripts/python.exe -B scripts/prepare_hotaru_assets.py
"""
from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / '[無碼] 天津罪（アマツツミ）'
CACHE = ROOT / 'extracted/amatsutsumi/assets'
TOOLS = ROOT / 'extracted/amatsutsumi/tools/GARbro'
OUTPUT = ROOT / 'backend/media/character/stage'
SOURCE_ENTRY = '04_ほたる\\st-hot_a102.pb3'
BACKGROUND_ENTRY = 'pb3\\bg110a.pb3'
RAR_SHA256 = 'c0e64b881f967e0a1473127b1d181c0808068a47e99d8b5f1fbe2d99a6b2ed53'
# These are descriptions of visually inspected pixels, not official emotion labels.
EXPRESSIONS = {
    'neutral': ('st-hot_a101', 'Eyes open, closed neutral mouth'),
    'smile': ('st-hot_a102', 'Eyes open, small closed-mouth smile'),
    'speaking': ('st-hot_a103', 'Eyes open, open smiling mouth'),
    'closed-eyes-smile': ('st-hot_a104', 'Closed eyes, open smiling mouth'),
    'surprised': ('st-hot_a112', 'Wide-open eyes and mouth'),
    'eyes-closed': ('st-hot_a113', 'Closed eyes and small closed mouth'),
    'blushing': ('st-hot_a120', 'Visible blush, mouth closed'),
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
    path.write_bytes(data)


def relative(path):
    return Path(path).relative_to(ROOT).as_posix()


def adapter():
    source = ROOT / 'scripts/amatsutsumi_garbro.cs'
    for name in ('GameRes.dll', 'ArcFormats.dll', 'GameData/Formats.dat', 'LICENSE.txt'):
        if not (TOOLS / name).is_file():
            raise ValueError('Official GARbro portable dependency is missing: ' + str(TOOLS / name))
    compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    framework = compiler.parent
    binary = TOOLS / 'HotaruAssets.exe'
    subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:' + str(binary),
                    '/r:' + str(TOOLS / 'GameRes.dll'), '/r:System.Web.Extensions.dll',
                    '/r:System.Xaml.dll', '/r:' + str(framework / 'WPF/PresentationCore.dll'),
                    '/r:' + str(framework / 'WPF/WindowsBase.dll'), str(source)], check=True)
    return binary


def command(binary, *args):
    result = subprocess.run([str(binary), *(str(arg) for arg in args)], capture_output=True, encoding='utf-8')
    if result.returncode:
        raise ValueError(result.stderr)
    return [json.loads(line.lstrip('\ufeff')) for line in result.stdout.splitlines() if line.strip()]


def save_webp(path, image, quality):
    data = BytesIO()
    image.save(data, format='WEBP', quality=quality, method=6)
    encoded = data.getvalue()
    # This script is idempotent, but never silently replaces a changed asset.
    if path.exists() and path.read_bytes() != encoded:
        raise ValueError('Refusing to overwrite differing Hotaru asset: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(encoded)


def validate_outputs(manifest):
    checked = []
    for row in manifest:
        path = ROOT / row['path']
        if not path.is_file() or sha(path) != row['sha256']:
            raise ValueError('Generated asset SHA mismatch: ' + str(path))
        with Image.open(path) as image:
            image.load()
            if list(image.size) != row['size']:
                raise ValueError('Generated asset dimensions differ')
            if row['kind'] in ('portrait', 'avatar', 'expression'):
                alpha = image.convert('RGBA').getchannel('A')
                if alpha.getextrema() != (0, 255) or not alpha.getbbox():
                    raise ValueError('Character alpha is missing or empty')
        checked.append(row['path'])
    return {'status': 'passed', 'decoded_files': len(checked), 'checked_paths': checked,
            'alpha_and_dimensions_checked': True, 'AI_generation': False}


def validate_expression_manifest(evidence):
    item = evidence['expression_manifest']
    path = ROOT / item['path']
    if sha(path) != item['sha256']:
        raise ValueError('Expression manifest SHA mismatch')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest['character_id'] != 'hotaru' or manifest['frames'] != evidence['expressions']:
        raise ValueError('Expression manifest differs from provenance')
    for frame in manifest['frames']:
        if not frame['url'].startswith('/media/character/stage/hotaru-'):
            raise ValueError('Expression URL outside this character')
        if not (ROOT / 'backend' / frame['url'].lstrip('/')).is_file():
            raise ValueError('Expression URL missing its file')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    provenance_path = OUTPUT / 'hotaru-provenance.json'
    if args.verify_only:
        evidence = json.loads(provenance_path.read_text(encoding='utf-8'))
        result = validate_outputs(evidence['outputs'])
        validate_expression_manifest(evidence)
        for archive in evidence['archives']:
            if sha(ROOT / archive['path']) != archive['sha256']:
                raise ValueError('Original game archive changed')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # Freeze existing role assets/provenance before creating only Hotaru outputs.
    frozen = {relative(p): sha(p) for p in OUTPUT.glob('*') if p.is_file() and not p.name.startswith('hotaru-')}
    binary = adapter()
    CACHE.mkdir(parents=True, exist_ok=True)
    stand_archive, background_archive = GAME / 'data/pack/stand.cpz', GAME / 'data/pack/bg.cpz'
    archives = [{'path': relative(p), 'sha256': sha(p), 'bytes': p.stat().st_size}
                for p in (stand_archive, background_archive)]
    stand = command(binary, 'extract', stand_archive, CACHE / 'stand', '04_ほたる')
    backgrounds = command(binary, 'extract', background_archive, CACHE / 'bg', 'pb3\\bg110a')
    write_json(CACHE / 'hotaru_stand_extraction.json', stand)
    write_json(CACHE / 'hotaru_background_extraction.json', backgrounds)
    # The PB3 difference decoder resolves the actual named base image from disk.
    command(binary, 'image-batch', CACHE / 'stand/04_ほたる', CACHE / 'decoded', 'st-hot_a1*.pb3')
    command(binary, 'image-batch', CACHE / 'bg/pb3', CACHE / 'decoded_bg', 'bg110a.pb3')

    main_source = CACHE / 'decoded/st-hot_a102.png'
    portrait = Image.open(main_source).convert('RGBA')
    bounds = portrait.getbbox()
    if not bounds:
        raise ValueError('Empty game portrait')
    rendered = portrait.crop(bounds)
    rendered.thumbnail((800, 1600), Image.Resampling.LANCZOS)
    save_webp(OUTPUT / 'hotaru-portrait.webp', rendered, 90)
    avatar_bounds = (14, 330, 442, 758)
    avatar = portrait.crop(avatar_bounds)
    avatar.thumbnail((384, 384), Image.Resampling.LANCZOS)
    save_webp(OUTPUT / 'hotaru-avatar.webp', avatar, 88)
    background = Image.open(CACHE / 'decoded_bg/bg110a.png').convert('RGB')
    background.thumbnail((1600, 900), Image.Resampling.LANCZOS)
    save_webp(OUTPUT / 'hotaru-background.webp', background, 86)

    expression_rows = []
    for name, (stem, description) in EXPRESSIONS.items():
        frame = Image.open(CACHE / 'decoded' / (stem + '.png')).convert('RGBA').crop(bounds)
        frame.thumbnail((800, 1600), Image.Resampling.LANCZOS)
        destination = OUTPUT / ('hotaru-' + name + '.webp')
        save_webp(destination, frame, 90)
        expression_rows.append({'name': name, 'url': '/media/' + destination.relative_to(ROOT / 'backend/media').as_posix(),
                                'source_entry': '04_ほたる\\' + stem + '.pb3',
                                'visual_description': description, 'official_emotion_label': False})
    outputs = []
    paths = [('portrait', OUTPUT / 'hotaru-portrait.webp'), ('avatar', OUTPUT / 'hotaru-avatar.webp'),
             ('background', OUTPUT / 'hotaru-background.webp')]
    paths += [('expression', OUTPUT / ('hotaru-' + name + '.webp')) for name in EXPRESSIONS]
    for kind, path in paths:
        with Image.open(path) as image:
            outputs.append({'path': relative(path), 'kind': kind, 'bytes': path.stat().st_size,
                            'size': list(image.size), 'sha256': sha(path)})
    manual = GAME / 'manual/img/ch05.jpg'
    input_rows = {r['name']: r for r in stand + backgrounds}
    source_names = {SOURCE_ENTRY, '04_ほたる\\st-hot_a101.pb3', BACKGROUND_ENTRY}
    source_names.update(r['source_entry'] for r in expression_rows)
    evidence = {
        'character_id': 'hotaru', 'name': '水无月萤', 'original_name': '水無月ほたる',
        'original_game': 'アマツツミ', 'date': '2026-10-23', 'AI_generated': False,
        'identity_evidence': {'path': relative(manual), 'sha256': sha(manual),
                              'method': 'Original manual names the character; visually matched face, hair/ribbons and uniform to archive folder 04_ほたる.'},
        'archives': archives,
        'source_entries': [dict(input_rows[name], archive='bg.cpz' if name == BACKGROUND_ENTRY else 'stand.cpz') for name in sorted(source_names)],
        'character_raw_extracted_files': len(stand),
        'portrait_source': SOURCE_ENTRY, 'portrait_crop': list(bounds), 'avatar_crop': list(avatar_bounds),
        'background_source': BACKGROUND_ENTRY,
        'background_choice': 'Visually inspected warm cafe interior from original bg.cpz. Stage setting only; not a claim about Hotaru residence or exact scene.',
        'expression_method': 'GARbro PB3 v6 named-base resolution. Original base plus original binary difference, no synthetic redraw.',
        'expressions': expression_rows,
        'outputs': outputs,
        'decoder': {'official_release': 'https://github.com/morkt/GARbro/releases/tag/v1.5.44',
                    'release_download': 'https://github.com/morkt/GARbro/releases/download/v1.5.44/GARbro-v1.5.44.2904.rar',
                    'download_sha256': RAR_SHA256,
                    'library_sha256': {name: sha(TOOLS / name) for name in ('GameRes.dll', 'ArcFormats.dll', 'GameData/Formats.dat')},
                    'image_format_source': 'https://github.com/morkt/GARbro/blob/master/ArcFormats/Cmvs/ImagePB3.cs',
                    'license_file': relative(TOOLS / 'LICENSE.txt'),
                    'local_adapter': 'scripts/amatsutsumi_garbro.cs', 'adapter_source_sha256': sha(ROOT / 'scripts/amatsutsumi_garbro.cs')},
        'existing_role_asset_hashes_unchanged': all(sha(ROOT / p) == digest for p, digest in frozen.items()),
    }
    if not evidence['existing_role_asset_hashes_unchanged']:
        raise ValueError('An existing role asset changed')
    for row in archives:
        if sha(ROOT / row['path']) != row['sha256']:
            raise ValueError('An original archive changed')
    expression_manifest = OUTPUT / 'hotaru-expressions.json'
    write_json(expression_manifest, {'character_id': 'hotaru', 'frames': expression_rows,
                                     'not_an_animation_or_lip_sync_model': True})
    evidence['expression_manifest'] = {'path': relative(expression_manifest), 'sha256': sha(expression_manifest)}
    evidence['validation'] = validate_outputs(outputs)
    validate_expression_manifest(evidence)
    write_json(provenance_path, evidence)
    print(json.dumps({'status': 'passed', 'outputs': outputs, 'raw_character_files': len(stand),
                      'provenance': str(provenance_path)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
