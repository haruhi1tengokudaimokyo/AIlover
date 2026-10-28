"""Summarize completed artifacts from their actual saved reports; no invented scores."""
from pathlib import Path
import json
from zipfile import ZipFile

OUT = Path(__file__).resolve().parents[2] / '训练成果/AutoDL_四角色'
NAMES = {'mugi': '麦', 'hotaru': '水无月萤', 'hika': '绯华', 'ayame': '菖蒲'}


def read_member(entry, member):
    with ZipFile(entry['local_path']) as archive:
        return json.loads(archive.read(member))


def main():
    entries = json.loads((OUT / '已校验成果.json').read_text(encoding='utf-8'))
    required = {(r, k) for r in NAMES for k in ('text', 'voice')}
    if not required <= {(e.get('role'), e.get('kind')) for e in entries}:
        print('Waiting for the active local verifier to finish rebuilding its checked-artifact index.')
        return
    rows = []
    for role, name in NAMES.items():
        text = next(e for e in entries if e.get('role') == role and e.get('kind') == 'text')
        voice = next(e for e in entries if e.get('role') == role and e.get('kind') == 'voice')
        summary = read_member(text, role + '/summary.json')
        coverage = read_member(text, role + '/train-coverage.json')
        voice_report = read_member(voice, role + '/training-complete.json')
        membership = read_member(voice, role + '/runtime-membership.json')
        baseline = next((e for e in entries if e.get('role') == role and e.get('kind') == 'baseline_text'), None)
        previous = read_member(baseline, role + '/summary.json') if baseline else None
        rows.append({'character': name, 'role': role, 'text_steps': summary['global_steps'],
            'text_validation_loss': summary['validation']['eval_loss'], 'text_test_loss': summary['test']['test_loss'],
            'text_unique_training_rows': coverage['unique_rows'],
            'baseline_validation_loss': previous['validation']['eval_loss'] if previous else None,
            'voice_train_source_rows': membership['source_train_utterances'],
            'voice_s1_rows': membership['stages']['s1']['included_count'],
            'voice_s2_rows': membership['stages']['s2']['included_count'],
            'voice_s1_epochs': voice_report['s1_epochs'], 'voice_s2_epochs': voice_report['s2_epochs']})
    receipt = OUT / '完整回传确认.json'
    report = {'roles': rows, 'all_artifacts_backup_receipt_present': receipt.exists(),
              'voice_listening_or_chinese_pronunciation_certified': False}
    (OUT / '四角色训练结果汇总.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# AIlover 四角色训练成果', '',
        '四角色文本LoRA与GPT-SoVITS v2Pro日语原声适配均完成。下表读取实际训练报告。', '',
        '| 角色 | 文本训练步数 | 实际覆盖文本条数 | 验证loss | 测试loss | 语音S1/S2实际条数 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        lines.append(f'| {row["character"]} | {row["text_steps"]} | {row["text_unique_training_rows"]} | '
            f'{row["text_validation_loss"]:.6f} | {row["text_test_loss"]:.6f} | {row["voice_s1_rows"]}/{row["voice_s2_rows"]} |')
    lines += ['', '文本包含LoRA、训练配置、分组数据审计、真实训练前后回答和分析。',
        '语音包含S1第3/6/9/12/15轮及S2第3/6/9/12轮推理权重、参考音频与日语原文、实际纳入/排除记录。',
        'S1和S2数量可能不同，保留了上游时长与音素速率过滤；未把日语音频改标为中文。', '',
        '## 效果如何理解', '',
        '文本loss越低表示对该保留语料的拟合更好，不能等同于更像角色或更好聊天。rank32并非必然优于rank8。',
        '麦和萤的首轮rank8模型一并保留，可与新版比较；不要无条件丢弃首轮模型。',
        '语音已完成参数适配，尚无中文合成听评或MOS/音色相似度认证。多个检查点需后续用固定中文句子试听选择，不能默认最后一轮最好。', '',
        '## 完整备份与关机', '',
        '共用底模包包含Qwen2.5-7B-Instruct、所需语音预训练模型、G2PW、字典和固定版本语音源码。',
        ('完整回传确认文件已生成；所有已登记包均通过本机SHA256与ZIP检查。' if receipt.exists() else
         '共用底模仍在回传或最终校验阶段；未生成完整回传确认前不得声称全部备份完成。'),
        '本地进度.json记录自动关机请求阶段；仅SSH断开不能单独证明平台停止计费。', '',
        '## 已校验文件', '', '| 文件 | 字节数 | SHA256 |', '| --- | ---: | --- |']
    for entry in entries:
        lines.append(f'| {Path(entry["local_path"]).name} | {entry["bytes"]} | {entry["sha256"]} |')
    (OUT / '先看这里_训练成果说明.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
