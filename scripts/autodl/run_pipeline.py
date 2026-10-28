"""Persistent remote controller: validate -> smoke -> full -> actual results."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path('/root/autodl-tmp/ailover')
RUN_ID = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def status(phase, **values):
    payload = {'run_id': RUN_ID, 'phase': phase, 'updated_utc': datetime.now(timezone.utc).isoformat(), **values}
    target = ROOT / 'reports/pipeline-status.json'
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temp.replace(target)
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def analyze(role, folder):
    summary = json.loads((folder / 'summary.json').read_text())
    before = json.loads((folder / 'baseline-answers.json').read_text())
    after = json.loads((folder / 'adapted-answers.json').read_text())
    history = json.loads((folder / 'trainer-log-history.json').read_text())
    validations = [{'step': r['step'], 'eval_loss': r['eval_loss']} for r in history if 'eval_loss' in r]
    def measures(rows):
        import re
        return {'answers': len(rows), 'empty': sum(not r['answer'].strip() for r in rows),
            'contains_japanese_kana': sum(bool(re.search('[ぁ-ヿ]', r['answer'])) for r in rows),
            'mean_answer_characters': sum(len(r['answer']) for r in rows) / max(1, len(rows))}
    result = {'role': role, 'source': 'actual completed training and generated held-out answers',
        'summary': summary, 'validation_curve': validations,
        'before': measures(before), 'after': measures(after),
        'role_fidelity_and_semantic_scores': 'not fabricated; inspect actual side-by-side answers',
        'test_used_for_training_or_checkpoint_selection': False}
    (folder / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    report = f'# {role}: 实际文本训练结果\n\n'
    report += f'训练步数：{summary["global_steps"]}；验证loss：{summary["validation"]["eval_loss"]:.6f}；测试loss：{summary["test"]["test_loss"]:.6f}。\n\n'
    report += f'峰值显存约{summary["peak_cuda_bytes"]/1024**3:.2f} GiB。验证集选择检查点：{summary["selected_checkpoint"]}。\n\n'
    report += '以下是实际模型输出，未用来补充训练数据或调参。loss和格式指标不能证明角色还原更好；还需人工逐题审阅。\n\n'
    old = {r['case_id']: r for r in before}
    for row in after:
        report += f'## {row["case_id"]}\n\n输入：{json.dumps(row["input_messages"],ensure_ascii=False)}\n\n训练前：{old[row["case_id"]]["answer"]}\n\n训练后：{row["answer"]}\n\n'
    (folder / '训练分析.md').write_text(report, encoding='utf-8')
    files = [p for p in folder.rglob('*') if p.is_file() and 'checkpoints' not in p.relative_to(folder).parts]
    checks = {p.relative_to(folder).as_posix(): hashlib.file_digest(p.open('rb'), 'sha256').hexdigest() for p in files}
    (folder / 'SHA256.json').write_text(json.dumps(checks, indent=2))
    archive = ROOT / 'outputs' / f'AIlover_{role}_Text_LoRA_{RUN_ID}.zip'
    with ZipFile(archive, 'x', ZIP_DEFLATED, compresslevel=1) as z:
        for p in folder.rglob('*'):
            if p.is_file() and 'checkpoints' not in p.relative_to(folder).parts:
                z.write(p, role + '/' + p.relative_to(folder).as_posix())
        for p in (ROOT / 'code').glob('*'):
            if p.is_file():
                z.write(p, 'training_code/' + p.name)
        z.write(ROOT / 'reports/text-environment.txt', 'training_code/text-environment.txt')
    with ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('Result ZIP integrity failure')
    return {'archive': str(archive), 'bytes': archive.stat().st_size,
            'sha256': hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()}


def main():
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    status('waiting_for_model_and_verified_data')
    start = time.monotonic()
    while not all((ROOT / 'reports' / n).is_file() for n in ('bootstrap-ready.json', 'data-ready.json')):
        if time.monotonic() - start > 7200:
            raise TimeoutError('Preparation did not finish within two hours; inspect bootstrap and data logs')
        time.sleep(15)
    py = ROOT / 'envs/text/bin/python'
    artifacts = []
    for role in ('mugi', 'hotaru'):
        # User requested direct formal training after verified data/model readiness.
        for phase in ('full',):
            status('text_' + phase, role=role, completed_artifacts=artifacts)
            log = ROOT / 'logs' / f'{role}-{phase}-{RUN_ID}.log'
            with log.open('w') as stream:
                result = subprocess.run([str(py), '-u', str(ROOT / 'code/train_text.py'), '--role', role,
                    '--phase', phase, '--run-id', RUN_ID], stdout=stream, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(f'{role}/{phase} failed; preserved exact log at {log}')
        artifacts.append(analyze(role, ROOT / 'outputs' / role / ('full-' + RUN_ID)))
    status('text_training_and_result_analysis_complete', artifacts=artifacts,
           voice_status='original Japanese data verified; separate speech adaptation workflow required')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        status('failed', error=str(exc), traceback=traceback.format_exc())
        raise
