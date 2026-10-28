"""Serial four-role full-data training, durable results, local-backup-gated shutdown."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

import run_pipeline as text_pipeline

ROOT = Path('/root/autodl-tmp/ailover')
SOURCE = ROOT / 'code/upstream/GPT-SoVITS-b4570b876f5c086819ba84e3215472733c6a7b70'
ROLES = ('mugi', 'hotaru', 'hika', 'ayame')
JOB = ROOT / 'reports/overnight-job.json'
RUN_ID = json.loads(JOB.read_text())['run_id'] if JOB.exists() else 'quality-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
TEXT_PY = ROOT / 'envs/text/bin/python'
VOICE_PY = ROOT / 'envs/speech/bin/python'
ARTIFACTS = []


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def state(phase, **values):
    value = {'run_id': RUN_ID, 'phase': phase, 'updated_utc': datetime.now(timezone.utc).isoformat(), **values}
    save(ROOT / 'reports/overnight-status.json', value)
    print(json.dumps(value, ensure_ascii=False), flush=True)


def publish(status='running'):
    save(ROOT / 'reports/overnight-artifacts.json', {'run_id': RUN_ID, 'status': status, 'artifacts': ARTIFACTS})


def fingerprint(path, **metadata):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'archive': str(path), 'bytes': path.stat().st_size, 'sha256': digest, **metadata}


def execute(label, command, cwd=ROOT, env=None, timeout=14400):
    state(label)
    path = ROOT / 'logs' / (label + '-' + RUN_ID + '.log')
    with path.open('a') as stream:
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
            stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{label} failed; full evidence: {path}')


def wait_for(label, ready, seconds=14400):
    state(label)
    start = time.monotonic()
    while not ready():
        if time.monotonic() - start > seconds:
            raise TimeoutError(label + ' exceeded waiting deadline')
        time.sleep(15)


def speech(role):
    root = ROOT / 'speech' / role
    summary = root / 'training-complete.json'
    archive = ROOT / 'outputs' / f'AIlover_{role}_Voice_v2Pro_Full_{RUN_ID}.zip'
    if summary.exists() and archive.exists():
        return fingerprint(archive, role=role, kind='voice')
    config = json.loads((root / 'configs/feature-environment.json').read_text())
    exp = Path(config['opt_dir'])
    exp.mkdir(parents=True, exist_ok=True)
    # Upstream webui creates this before invoking s2_train; the CLI does not.
    (exp / 'logs_s2_v2Pro').mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **config, 'CUDA_VISIBLE_DEVICES': '0',
        'PYTHONPATH': str(SOURCE) + ':' + str(SOURCE / 'GPT_SoVITS'), 'hz': '25hz',
        'PATH': str(VOICE_PY.parent) + ':' + os.environ['PATH'], 'TOKENIZERS_PARALLELISM': 'false'}
    names = {Path(line.split('|')[0]).name for line in Path(config['inp_text']).read_text().splitlines() if line.strip()}
    if len(names) != len([line for line in Path(config['inp_text']).read_text().splitlines() if line.strip()]):
        raise ValueError('Duplicate audio basename would overwrite feature files')
    stages = [('text', '1-get-text.py'), ('hubert', '2-get-hubert-wav32k.py'),
              ('speaker', '2-get-sv.py'), ('semantic', '3-get-semantic.py')]
    for label, script in stages:
        execute(role + '-features-' + label, [VOICE_PY, '-s', SOURCE / 'GPT_SoVITS/prepare_datasets' / script], SOURCE, env)
    phonemes = exp / '2-name2text-0.txt'
    semantics = exp / '6-name2semantic-0.tsv'
    (exp / '2-name2text.txt').write_text(phonemes.read_text(), encoding='utf-8')
    (exp / '6-name2semantic.tsv').write_text('item_name\tsemantic_audio\n' + semantics.read_text().rstrip('\n') + '\n', encoding='utf-8')
    feature_sets = {'phoneme': {r.split('\t')[0] for r in phonemes.read_text().splitlines() if r.strip()},
        'semantic': {r.split('\t')[0] for r in semantics.read_text().splitlines() if r.strip()}}
    for folder, suffix in [('4-cnhubert', '.pt'), ('5-wav32k', ''), ('7-sv_cn', '.pt')]:
        feature_sets[folder] = {p.name[:-len(suffix)] if suffix else p.name for p in (exp / folder).iterdir() if p.is_file()}
    missing = {k: sorted(names - v) for k, v in feature_sets.items() if names - v}
    save(root / 'feature-completeness.json', {'expected': len(names), 'missing': missing})
    if missing:
        raise ValueError(f'{role}: upstream skipped features; exact missing IDs recorded, no silent omissions')
    execute(role + '-runtime-membership', [VOICE_PY, ROOT / 'code/audit_speech_runtime.py',
        '--source', SOURCE, '--role-root', root], SOURCE, env)
    for directory in ('weights/SoVITS_v2Pro', 'weights/GPT_v2Pro'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    if not list((root / 'weights/SoVITS_v2Pro').glob('*_e12_*.pth')):
        execute(role + '-voice-S2', [VOICE_PY, '-s', SOURCE / 'GPT_SoVITS/s2_train.py', '--config', root / 'configs/s2-v2pro.json'], SOURCE, env)
    if not list((root / 'weights/GPT_v2Pro').glob('*-e15.ckpt')):
        execute(role + '-voice-S1', [VOICE_PY, '-s', SOURCE / 'GPT_SoVITS/s1_train.py', '--config_file', root / 'configs/s1-v2pro.yaml'], SOURCE, env)
    if not list((root / 'weights/SoVITS_v2Pro').glob('*_e12_*.pth')) or not list((root / 'weights/GPT_v2Pro').glob('*-e15.ckpt')):
        raise RuntimeError('Expected final-epoch inference weights missing')
    result = {'status': 'trained', 'role': role, 'method': 'official v2Pro S2 and S1 full-train-split adaptation',
        's2_epochs': 12, 's1_epochs': 15, 'audio_language': 'ja', 'actual_chinese_recordings': 0,
        'chinese_synthesis_quality': 'not yet established by listening; no invented score',
        'checkpoint_selection': 'all scheduled inference checkpoints retained for subsequent Chinese listening evaluation',
        'upstream_has_independent_validation': False,
        'heldout_validation_test': 'preserved outside update data; not automatically scored by upstream S1/S2 trainer'}
    save(summary, result)
    package = Path(json.loads((ROOT / 'reports/data-ready.json').read_text())[role]['voice'])
    with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=1) as z:
        for directory in ('weights', 'configs'):
            for path in (root / directory).rglob('*'):
                if path.is_file():
                    z.write(path, role + '/' + path.relative_to(root).as_posix())
        for path in root.glob('*.json'):
            z.write(path, role + '/' + path.name)
        for path in exp.rglob('events.out.tfevents.*'):
            z.write(path, role + '/events/' + path.relative_to(exp).as_posix())
        reference = package / 'references' / (role + '.json')
        if reference.exists():
            z.write(reference, role + '/references/references.json')
            for row in json.loads(reference.read_text()):
                wav = package / row['audio_path']
                z.write(wav, role + '/references/' + wav.name)
        for path in (ROOT / 'code').glob('*.py'):
            z.write(path, 'training_code/' + path.name)
        z.write(ROOT / 'reports/speech-environment.txt', 'training_code/speech-environment.txt')
    with ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('Voice result ZIP CRC failure')
    return fingerprint(archive, role=role, kind='voice')


def shared_base():
    archive = ROOT / 'outputs' / ('AIlover_Shared_Base_Models_' + RUN_ID + '.zip')
    if archive.exists():
        with ZipFile(archive) as z:
            if z.testzip():
                raise ValueError('Shared base archive damaged')
        return fingerprint(archive, kind='shared_base')
    sources = [(ROOT / 'models/Qwen2.5-7B-Instruct', 'Qwen2.5-7B-Instruct'),
               (SOURCE / 'GPT_SoVITS/pretrained_models', 'GPT-SoVITS/GPT_SoVITS/pretrained_models'),
               (SOURCE / 'GPT_SoVITS/text/G2PWModel', 'GPT-SoVITS/GPT_SoVITS/text/G2PWModel')]
    size = sum(p.stat().st_size for base, _ in sources for p in base.rglob('*') if p.is_file())
    if shutil.disk_usage(ROOT).free < size + 3 * 1024**3:
        raise RuntimeError('Not enough disk for complete dependency archive')
    with ZipFile(archive, 'w', ZIP_STORED) as z:
        for base, label in sources:
            for path in base.rglob('*'):
                if path.is_file() and '._____temp' not in path.parts and '.cache' not in path.parts:
                    z.write(path, label + '/' + path.relative_to(base).as_posix())
        z.write(ROOT / 'code/speech-source-lock.json', 'speech-source-lock.json')
        z.write(ROOT / 'code/GPT-SoVITS-b4570b8.zip', 'GPT-SoVITS-source.zip')
        for name in ('nltk_data.zip', 'open_jtalk_dic_utf_8-1.11.tar.gz'):
            z.write(ROOT / 'incoming/speech-base' / name, 'dictionaries/' + name)
    with ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('Shared dependencies CRC failure')
    return fingerprint(archive, kind='shared_base')


def main():
    global ARTIFACTS
    save(JOB, {'run_id': RUN_ID, 'roles': ROLES, 'text_profile': 'quality', 'voice_input': 'full_train'})
    manifest = ROOT / 'reports/overnight-artifacts.json'
    if manifest.exists():
        ARTIFACTS = json.loads(manifest.read_text()).get('artifacts', [])
    publish()
    wait_for('waiting_for_existing_formal_text_job', lambda: json.loads(
        (ROOT / 'reports/pipeline-status.json').read_text())['phase'] in ('text_training_and_result_analysis_complete', 'failed'))
    baseline = json.loads((ROOT / 'reports/pipeline-status.json').read_text())
    for index, entry in enumerate(baseline.get('artifacts', baseline.get('completed_artifacts', []))):
        entry = {**entry, 'role': ('mugi', 'hotaru')[index], 'kind': 'baseline_text'}
        if entry['archive'] not in {e['archive'] for e in ARTIFACTS}:
            ARTIFACTS.append(entry)
    publish()
    wait_for('waiting_for_four_verified_packages', lambda: set(ROLES) <= set(json.loads((ROOT / 'reports/data-ready.json').read_text())))
    text_pipeline.RUN_ID = RUN_ID
    os.environ.update(TOKENIZERS_PARALLELISM='false', CUDA_VISIBLE_DEVICES='0')
    for role in ROLES:
        if any(e.get('role') == role and e.get('kind') == 'text' for e in ARTIFACTS):
            continue
        folder = ROOT / 'outputs' / role / ('full-' + RUN_ID)
        if not (folder / 'summary.json').exists():
            command = [TEXT_PY, ROOT / 'code/train_text.py', '--role', role, '--phase', 'full',
                       '--run-id', RUN_ID, '--profile', 'quality']
            checkpoints = sorted((folder / 'checkpoints').glob('checkpoint-*'), key=lambda p: int(p.name.split('-')[-1]))
            if checkpoints:
                command += ['--resume', checkpoints[-1]]
            execute(role + '-text-quality', command)
        archive = ROOT / 'outputs' / f'AIlover_{role}_Text_LoRA_{RUN_ID}.zip'
        result = fingerprint(archive) if archive.exists() else text_pipeline.analyze(role, folder)
        ARTIFACTS.append({**result, 'role': role, 'kind': 'text'})
        publish()
    wait_for('waiting_for_speech_environment_and_assets', lambda: (ROOT / 'reports/speech-assets-ready.json').exists())
    execute('prepare-full-speech-configs', [TEXT_PY, ROOT / 'code/prepare_speech.py', '--roles', *ROLES, '--full'])
    for role in ROLES:
        if not any(e.get('role') == role and e.get('kind') == 'voice' for e in ARTIFACTS):
            ARTIFACTS.append(speech(role))
            publish()
    if not any(e.get('kind') == 'shared_base' for e in ARTIFACTS):
        state('packaging_complete_shared_base_models')
        ARTIFACTS.append(shared_base())
    publish('all_complete')
    state('all_trained_waiting_for_verified_local_backup', artifacts=ARTIFACTS)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        state('failed_no_shutdown', traceback=traceback.format_exc())
        publish('failed_no_shutdown')
        raise
