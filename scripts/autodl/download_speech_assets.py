"""Fetch official install.sh ModelScope assets, with hashes and selective extraction."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from zipfile import ZipFile

ROOT = Path('/root/autodl-tmp/ailover')
SOURCE = ROOT / 'code/upstream/GPT-SoVITS-b4570b876f5c086819ba84e3215472733c6a7b70'
BASE = 'https://www.modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/master/'


def safe(target, name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe archive name: ' + name)
    result = target.joinpath(*p.parts)
    if not result.resolve().is_relative_to(target.resolve()):
        raise ValueError('Archive path escape')
    return result


def main():
    import pyopenjtalk
    incoming = ROOT / 'incoming/speech-base'
    incoming.mkdir(parents=True, exist_ok=True)
    keep = ('pretrained_models/chinese-roberta-wwm-ext-large/',
            'pretrained_models/chinese-hubert-base/',
            'pretrained_models/v2Pro/s2Gv2Pro.pth',
            'pretrained_models/v2Pro/s2Dv2Pro.pth',
            'pretrained_models/sv/', 'pretrained_models/s1v3.ckpt')
    records = []
    for name in ('pretrained_models.zip', 'G2PWModel.zip', 'nltk_data.zip',
                 'open_jtalk_dic_utf_8-1.11.tar.gz'):
        if shutil.disk_usage(ROOT).free < 25 * 1024**3:
            raise RuntimeError('Less than 25 GiB free; preserve space for active text training')
        path = incoming / name
        partial = path.with_suffix(path.suffix + '.part')
        if not path.exists():
            print('FETCHING_OFFICIAL_ASSET', name, flush=True)
            subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--connect-timeout', '20',
                '--max-time', '7200', '--limit-rate', '3M', '--max-filesize', str(20 * 1024**3),
                '--continue-at', '-', '--output', str(partial), BASE + name], check=True)
            partial.replace(path)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        record = {'file': str(path), 'url': BASE + name, 'bytes': path.stat().st_size,
                  'sha256': digest, 'extracted': [], 'not_required_for_v2pro': []}
        if name.endswith('.zip'):
            target = (SOURCE / 'GPT_SoVITS' if name == 'pretrained_models.zip' else
                      SOURCE / 'GPT_SoVITS/text' if name == 'G2PWModel.zip' else Path(sys.prefix))
            with ZipFile(path) as archive:
                if archive.testzip():
                    raise ValueError('Corrupt ZIP: ' + name)
                members = archive.infolist()
                selected = [m for m in members if not m.is_dir() and
                            (name != 'pretrained_models.zip' or any(m.filename.startswith(k) for k in keep))]
                size = sum(m.file_size for m in selected)
                if shutil.disk_usage(ROOT).free < size + 15 * 1024**3:
                    raise RuntimeError('Insufficient free space for safe extraction')
                for member in members:
                    safe(target, member.filename)
                for member in selected:
                    destination = safe(target, member.filename)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as src, destination.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
                    record['extracted'].append(member.filename)
                record['not_required_for_v2pro'] = [m.filename for m in members if not m.is_dir() and m not in selected]
        else:
            target = Path(pyopenjtalk.__file__).parent
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    safe(target, member.name)
                    if not member.isfile() and not member.isdir():
                        raise ValueError('Dictionary archive contains a special file')
                archive.extractall(target, filter='data')
            record['extracted'] = ['open_jtalk_dic_utf_8-1.11']
        records.append(record)
        (ROOT / 'reports/speech-assets-progress.json').write_text(json.dumps(records, indent=2))
    required = ['s1v3.ckpt', 'v2Pro/s2Gv2Pro.pth', 'v2Pro/s2Dv2Pro.pth',
                'sv/pretrained_eres2netv2w24s4ep4.ckpt',
                'chinese-roberta-wwm-ext-large/config.json', 'chinese-hubert-base/config.json']
    for name in required:
        if not (SOURCE / 'GPT_SoVITS/pretrained_models' / name).is_file():
            raise FileNotFoundError('Official archive lacks required asset: ' + name)
    (ROOT / 'reports/speech-assets-ready.json').write_text(json.dumps({
        'status': 'downloaded_and_checked', 'records': records, 'gpu_training_started': False}, indent=2))
    print('SPEECH_BASE_ASSETS_READY', flush=True)


if __name__ == '__main__':
    main()
