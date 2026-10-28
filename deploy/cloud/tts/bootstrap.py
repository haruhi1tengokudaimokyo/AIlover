"""Verify the mounted assets before importing speech code; prepare dictionaries."""
import hashlib
import json
import os
from pathlib import Path
import tarfile
from zipfile import ZipFile


def prepare(root):
    inventory = json.loads((root / 'SHA256.json').read_text())
    for name, expected in inventory.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Invalid asset inventory path')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected['sha256']:
                raise ValueError('Asset integrity failure')
    for folder, target in ((root / 'common', Path('/app/gsv/GPT_SoVITS/pretrained_models')),
                           (root / 'G2PWModel', Path('/app/gsv/GPT_SoVITS/text/G2PWModel'))):
        for source in folder.rglob('*'):
            if source.is_file():
                dest = target / source.relative_to(folder)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    dest.symlink_to(source)
                elif dest.resolve() != source.resolve():
                    with dest.open('rb') as existing, source.open('rb') as original:
                        if hashlib.file_digest(existing, 'sha256').digest() != hashlib.file_digest(original, 'sha256').digest():
                            raise ValueError('Conflicting baked-in model asset')
    dictionaries = Path('/tmp/ailover-dictionaries')
    dictionaries.mkdir(exist_ok=True)
    with tarfile.open(root / 'dictionaries/open_jtalk_dic_utf_8-1.11.tar.gz') as archive:
        archive.extractall(dictionaries, filter='data')
    with ZipFile(root / 'dictionaries/nltk_data.zip') as archive:
        for item in archive.namelist():
            if not (dictionaries / item).resolve().is_relative_to(dictionaries):
                raise ValueError('Invalid dictionary member')
        archive.extractall(dictionaries)
    os.environ['OPEN_JTALK_DICT_DIR'] = str(dictionaries / 'open_jtalk_dic_utf_8-1.11')
    os.environ['NLTK_DATA'] = str(dictionaries / 'nltk_data')
    return {'assets_verified': len(inventory), 'model_roles': ['hika', 'ayame', 'mugi', 'hotaru']}
