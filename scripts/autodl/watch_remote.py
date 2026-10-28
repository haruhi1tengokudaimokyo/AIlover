"""Read-only terminal dashboard for the actual remote processes and logs."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import re
import shutil
import subprocess
import time

ROOT = Path('/root/autodl-tmp/ailover')


def tail(path, size=24000):
    try:
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - size))
            raw = stream.read().decode('utf-8', errors='replace')
        return re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', raw)
    except FileNotFoundError:
        return ''


def main():
    while True:
        print('\033[2J\033[H', end='')
        print('AIlover | AutoDL live status | ' + datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S +08:00'))
        print('=' * 88)
        try:
            state = json.loads((ROOT / 'reports/pipeline-status.json').read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        names = {'waiting_for_model_and_verified_data': 'Downloading base model; formal training starts automatically',
                 'text_full': 'FORMAL TEXT TRAINING', 'failed': 'FAILED: inspect error below',
                 'text_training_and_result_analysis_complete': 'TEXT TRAINING AND ANALYSIS COMPLETE'}
        print('Stage:', names.get(state.get('phase'), state.get('phase', 'starting')))
        print('Role:', state.get('role', '-'), '| Run:', state.get('run_id', '-'))
        overnight = ROOT / 'reports/overnight-status.json'
        if overnight.exists():
            night = json.loads(overnight.read_text())
            phase = night.get('phase', '')
            labels = {'waiting_for_existing_formal_text_job': '等待当前正式训练完成，随后自动接续四角色新版训练',
                'waiting_for_four_verified_packages': '等待四角色材料校验',
                'waiting_for_speech_environment_and_assets': '等待语音预训练资产',
                'prepare-full-speech-configs': '建立四角色完整语音训练区配置',
                'packaging_complete_shared_base_models': '打包共用底模，准备回传本机',
                'all_trained_waiting_for_verified_local_backup': '训练完成，等待本机回传校验后自动关机',
                'failed_no_shutdown': '自动队列遇到错误；未关机，等待处理'}
            print('夜间自动队列:', labels.get(phase, phase))
            print('新版：四角色独立 rank32/alpha64 文本LoRA；完整语音训练区 S2=12轮、S1=15轮。')
        print('Plan: Mugi full training -> Hotaru full training -> actual analysis + result ZIPs')
        print('Separate smoke training: DISABLED. Validation/checkpoint saving: ENABLED.')
        if state.get('error'):
            print('ERROR:', state['error'])
        print('\nBASE MODEL DOWNLOAD (actual downloader output)')
        source = tail(ROOT / 'logs/bootstrap.log')
        for index in range(1, 5):
            matches = re.findall(r'Downloading \[model-' + f'{index:05d}' + r'-of-00004.safetensors\]:[^\r\n]*', source)
            print(matches[-1] if matches else f'Shard {index}: see bootstrap.log for previous/completed progress')
        if (ROOT / 'reports/bootstrap-ready.json').exists():
            print('BASE MODEL READY')
        print('\nGPU')
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.used,memory.total,utilization.gpu',
            '--format=csv,noheader'], capture_output=True, text=True)
        print(result.stdout.strip() or result.stderr.strip())
        print('\nLATEST TRAINING OUTPUT')
        logs = sorted([p for p in (ROOT / 'logs').glob('*.log') if '-full-' in p.name or
            '-text-quality-' in p.name or '-voice-S' in p.name or '-features-' in p.name], key=lambda p: p.stat().st_mtime)
        if logs:
            print(str(logs[-1]))
            lines = [s.strip() for s in re.split(r'[\r\n]+', tail(logs[-1])) if s.strip()]
            print('\n'.join(lines[-8:]))
        else:
            print('No training steps yet: base model is still downloading. No GPU time spent on tests.')
        print('\nSPEECH PREPARATION (separate environment, no speech training launched)')
        lines = [s.strip() for s in re.split(r'[\r\n]+', tail(ROOT / 'logs/speech-preparation.log', 5000)) if s.strip()]
        print('\n'.join(lines[-4:]))
        disk = shutil.disk_usage(ROOT)
        print(f'\nData disk: {(disk.total-disk.free)/1024**3:.1f} GiB used / {disk.total/1024**3:.1f} GiB total')
        print('Refresh: 10s | Closing this monitor does NOT stop screen-backed training.')
        print('Logs and reports: /root/autodl-tmp/ailover/{logs,reports,outputs}', flush=True)
        time.sleep(10)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nMonitor closed; remote training continues.')
