"""Prepare source-traceable GPT-SoVITS v2Pro runs; never train or relabel JA as ZH."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import wave
import argparse

ROOT = Path('/root/autodl-tmp/ailover')
COMMIT = 'b4570b876f5c086819ba84e3215472733c6a7b70'
SOURCE = ROOT / 'code/upstream' / ('GPT-SoVITS-' + COMMIT)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    import yaml
    parser = argparse.ArgumentParser()
    parser.add_argument('--roles', nargs='+', default=['mugi', 'hotaru'])
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    packages = json.loads((ROOT / 'reports/data-ready.json').read_text())
    reports = {}
    for role in args.roles:
        package = Path(packages[role]['voice'])
        output = ROOT / 'speech' / role
        lists = output / 'lists'
        lists.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, '-B', str(package / 'tools/verify.py'), 'paths',
                   '--root', str(package), '--output-dir', str(lists)]
        if role != 'hotaru':
            command.extend(['--character', role])
        subprocess.run(command, check=True)
        parsed = {}
        for split in ('train', 'validation', 'test', 'fewshot_15min'):
            candidates = [lists / (role + '_' + split + '.list'), lists / (split + '.list')]
            path = next((p for p in candidates if p.is_file()), None)
            if path is None:
                raise FileNotFoundError(candidates)
            rows = []
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                audio, speaker, language, text = line.split('|')
                audio = Path(audio)
                if not audio.is_absolute() or not audio.is_file() or language.lower() != 'ja' or speaker != role or not text.strip():
                    raise ValueError('Invalid identity/language/path: ' + line)
                with wave.open(str(audio)) as wav:
                    duration = wav.getnframes() / wav.getframerate()
                    if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 32000:
                        raise ValueError('Unexpected prepared audio format: ' + str(audio))
                with audio.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                rows.append({'audio': str(audio), 'sha256': digest, 'duration_seconds': duration,
                             'speaker': speaker, 'language': 'ja', 'transcript': text})
            parsed[split] = {'path': str(path), 'rows': rows}
        groups = {s: {r['sha256'] for r in parsed[s]['rows']} for s in parsed}
        for a, b in (('train', 'validation'), ('train', 'test'), ('validation', 'test')):
            if groups[a] & groups[b]:
                raise ValueError('Audio leakage: ' + a + '/' + b)
        if not groups['fewshot_15min'] <= groups['train']:
            raise ValueError('Few-shot subset is not strictly from training data')
        tag = 'v2pro-full' if args.full else 'v2pro-15min'
        exp = output / ('runs/' + tag)
        # These configs mirror the pinned upstream webui.py configuration fields.
        s2 = json.loads((SOURCE / 'GPT_SoVITS/configs/s2v2Pro.json').read_text())
        pretrained = SOURCE / 'GPT_SoVITS/pretrained_models'
        s2['train'].update(batch_size=4, epochs=12 if args.full else 8, text_low_lr_rate=.4,
            pretrained_s2G=str(pretrained / 'v2Pro/s2Gv2Pro.pth'),
            pretrained_s2D=str(pretrained / 'v2Pro/s2Dv2Pro.pth'),
            if_save_latest=True, if_save_every_weights=True, save_every_epoch=3 if args.full else 1,
            gpu_numbers='0', grad_ckpt=True, lora_rank=32)
        s2['model']['version'] = 'v2Pro'
        s2['data']['exp_dir'] = s2['s2_ckpt_dir'] = str(exp)
        s2.update(save_weight_dir=str(output / 'weights/SoVITS_v2Pro'),
                  name=role + '-' + tag, version='v2Pro')
        save(output / 'configs/s2-v2pro.json', s2)
        s1 = yaml.safe_load((SOURCE / 'GPT_SoVITS/configs/s1longer-v2.yaml').read_text())
        s1['train'].update(batch_size=4, epochs=15 if args.full else 8, save_every_n_epoch=3 if args.full else 1,
            if_save_every_weights=True, if_save_latest=True, if_dpo=False,
            half_weights_save_dir=str(output / 'weights/GPT_v2Pro'), exp_name=role + '-' + tag)
        s1.update(pretrained_s1=str(pretrained / 's1v3.ckpt'),
            train_semantic_path=str(exp / '6-name2semantic.tsv'),
            train_phoneme_path=str(exp / '2-name2text.txt'), output_dir=str(exp / 'logs_s1_v2Pro'))
        for key in ('lr', 'lr_init', 'lr_end'):
            s1['optimizer'][key] = float(s1['optimizer'][key])
        # PyYAML's YAML 1.1 loader reads JSON-style 1e-05 as str. Its own dumper
        # emits 1.0e-05, preserving numeric types for the upstream scheduler.
        (output / 'configs/s1-v2pro.yaml').write_text(
            yaml.safe_dump(s1, allow_unicode=True, sort_keys=False), encoding='utf-8')
        env = {'inp_text': parsed['train' if args.full else 'fewshot_15min']['path'], 'inp_wav_dir': '',
            'exp_name': role + '-' + tag, 'i_part': '0', 'all_parts': '1',
            '_CUDA_VISIBLE_DEVICES': '0', 'opt_dir': str(exp), 'is_half': 'True', 'version': 'v2Pro',
            'bert_pretrained_dir': str(pretrained / 'chinese-roberta-wwm-ext-large'),
            'cnhubert_base_dir': str(pretrained / 'chinese-hubert-base'),
            'pretrained_s2G': str(pretrained / 'v2Pro/s2Gv2Pro.pth'),
            'sv_path': str(pretrained / 'sv/pretrained_eres2netv2w24s4ep4.ckpt'),
            's2config_path': str(SOURCE / 'GPT_SoVITS/configs/s2v2Pro.json')}
        save(output / 'configs/feature-environment.json', env)
        save(output / 'audio-audit.json', parsed)
        reports[role] = {s: {'count': len(parsed[s]['rows']),
            'hours': sum(r['duration_seconds'] for r in parsed[s]['rows']) / 3600,
            'list': parsed[s]['path']} for s in parsed}
        reports[role]['status'] = 'prepared_not_trained'
        reports[role]['manual_listening'] = 'not certified; original provisional quality flags preserved'
    save(ROOT / 'reports/speech-data-ready.json', {'upstream_commit': COMMIT, 'roles': reports,
         'audio_language': 'ja', 'chinese_supervised_recordings_available': False,
         'purpose': 'Japanese voice adaptation, multilingual model to synthesize Chinese',
         'gpu_training_started': False})
    print('SPEECH_DATA_CONFIGS_READY', flush=True)


if __name__ == '__main__':
    main()
