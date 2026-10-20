"""Build local game portraits from the game's actual body/face/accessory layers.

No AI generation and no database writes. Outputs remain in gitignored media/.
Character IDs come from Init_VariableADV.ks: 2=緋華, 8=菖蒲.
Outfit layers follow Init_VariableSTAND.ks dr=1 and Macro_Stand.ks pimage order.
"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image
from tlg import tlg_to_image
from xp3 import extract_file, parse_index

ROOT = Path(__file__).resolve().parent.parent
CHARACTERS = {'hika': (2, 'bg1_0.png'), 'ayame': (8, 'bg4_0.png')}


def composite_layers(body, face, accessories=()):
    result = body.copy().convert('RGBA')
    # Game pimage uses dx=0, dy=0; do not crop layers before compositing.
    for layer in (face, *accessories):
        if layer.width > result.width or layer.height > result.height:
            raise ValueError('Layer dimensions exceed body canvas')
        result.alpha_composite(layer.convert('RGBA'), (0, 0))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, default=ROOT / '国王恋爱')
    parser.add_argument('--media-dir', type=Path, default=ROOT / 'backend/media')
    options = parser.parse_args()
    cache = ROOT / 'extracted/stage_metadata'
    cache.mkdir(parents=True, exist_ok=True)
    stand_archive, background_archive = options.game_dir / 'stimage.xp3', options.game_dir / 'bgimage.xp3'
    stands = {entry[0]: entry for entry in parse_index(stand_archive)}
    backgrounds = {entry[0]: entry for entry in parse_index(background_archive)}
    output = options.media_dir / 'character/stage'
    output.mkdir(parents=True, exist_ok=True)
    evidence = {}
    for slug, (number, background_name) in CHARACTERS.items():
        names = [f'2/stb{number}_s2_1_2.tlg', f'2/st{number}_s2_1_1.tlg', f'2/stp{number}_s2_1_1.tlg']
        layers, hashes = [], {}
        for name in names:
            source = cache / Path(name).name
            extract_file(stand_archive, stands[name], source)
            hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
            layers.append(tlg_to_image(source))
        portrait = composite_layers(layers[0], layers[1], layers[2:])
        bounds = portrait.getbbox()
        if bounds is None:
            raise ValueError('Empty character portrait')
        rendered = portrait.crop(bounds)
        rendered.thumbnail((800, 1600), Image.Resampling.LANCZOS)
        rendered.save(output / f'{slug}-portrait.webp', quality=90, method=6)
        face_box = layers[1].getbbox()
        if face_box is None:
            raise ValueError('Empty face layer')
        cx, cy = (face_box[0] + face_box[2]) // 2, (face_box[1] + face_box[3]) // 2
        half = int(max(face_box[2] - face_box[0], face_box[3] - face_box[1]) * .95)
        avatar = portrait.crop((cx-half, max(0, cy-half), cx+half, max(0, cy-half)+half*2))
        avatar.thumbnail((384, 384), Image.Resampling.LANCZOS)
        avatar.save(output / f'{slug}-avatar.webp', quality=88, method=6)
        background_source = cache / background_name
        extract_file(background_archive, backgrounds[background_name], background_source)
        background = Image.open(background_source).convert('RGB')
        background.thumbnail((1600, 900), Image.Resampling.LANCZOS)
        background.save(output / f'{slug}-background.webp', quality=86, method=6)
        evidence[slug] = {'character_id_in_game': number, 'layers': hashes,
                          'background': background_name, 'portrait_size': rendered.size,
                          'alpha_extrema': rendered.getchannel('A').getextrema()}
        print(f'Prepared {slug}: {rendered.width}x{rendered.height}', flush=True)
    (output / 'provenance.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
