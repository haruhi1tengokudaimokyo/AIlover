"""Prepare Mugi's local training sources without changing the two existing datasets.

Run from any directory with the project's Python 3.12 environment:
    .venv/Scripts/python.exe scripts/prepare_mugi_training.py

No model/API calls. Reuses the KAG parser, cleaning rules and GPT-SoVITS builder.
Game text/audio and generated datasets stay local; no training is performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from web.documents.utils.story_pipeline import parse_script
from build_character_data import clean_text, is_usable
from mugi_filter import mugi_training_usable
from xp3 import extract_file, parse_index


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def preceding_safe_context(row, indexed):
    return [c for c in row['context'] if c['id'] != row['id']
            and indexed[c['id']]['source_file'] == row['source_file']
            and indexed[c['id']]['segment'] == row['segment']
            and indexed[c['id']]['sequence'] < row['sequence']
            and mugi_training_usable(indexed[c['id']])]


def prepare_sources(source, game_dir, reuse_audio=False):
    out = ROOT / 'extracted/characters/mugi'
    out.mkdir(parents=True, exist_ok=True)
    all_rows, issues = [], []
    for path in sorted(source.rglob('*.ks')):
        rows, audit = parse_script(path, source)
        all_rows.extend(rows)
        issues.extend(audit)
    mine = [r for r in all_rows if r['speaker'] == 'むぎ']
    if not mine:
        raise ValueError('No Mugi dialogue; check --source directory/encoding')
    # Only the game-authoritative vo1 prefix is extracted. Other character audio is untouched.
    archive = game_dir / 'voice.xp3'
    prior = out / 'voice_provenance.jsonl'
    if reuse_audio:
        if not prior.is_file():
            raise ValueError('--reuse-audio requires a previous extraction manifest')
        evidence = [json.loads(line) for line in prior.read_text(encoding='utf-8').splitlines()]
        for record in evidence:
            name = record['archive_entry']
            if Path(name).name != name or not name.startswith('vo1_'):
                raise ValueError('Unexpected previous voice manifest path')
            path = ROOT / 'extracted/voice' / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('Previously extracted Mugi voice hash mismatch')
        entries = [(record['archive_entry'], None, None) for record in evidence]
    else:
        entries = [entry for entry in parse_index(archive) if entry[0].startswith('vo1_') and entry[0].endswith('.opus')]
    evidence = []
    for index, entry in enumerate(entries, 1):
        name = entry[0]
        if Path(name).name != name:
            raise ValueError('Unexpected nested voice entry')
        destination = ROOT / 'extracted/voice' / name
        if not destination.exists():
            extract_file(archive, entry, destination)
        if not destination.read_bytes().startswith(b'OggS'):
            raise ValueError(f'Invalid Opus container: {name}')
        evidence.append({'archive_entry': name, 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                         'bytes': destination.stat().st_size})
        if index % 300 == 0:
            print(f'Mugi audio extracted/validated: {index}/{len(entries)}', flush=True)
    write_jsonl(out / 'voice_provenance.jsonl', evidence)
    write_jsonl(out / 'source_records.jsonl', mine)
    compatible = [dict(r, file=Path(r['source_file']).name, char=r['speaker'], voice=r['voice_id']) for r in mine]
    write_jsonl(out / 'source_corpus.jsonl', compatible)
    subprocess.run([sys.executable, str(ROOT / 'scripts/build_character_data.py'), '--char', 'mugi',
                    '--corpus', str(out / 'source_corpus.jsonl'), '--out-root', str(out.parent)],
                   cwd=ROOT, check=True)
    kept = [json.loads(line) for line in (out / 'lines_clean.jsonl').read_text(encoding='utf-8').splitlines()]
    clean_by_id = {r['source_id']: r for r in kept}
    indexed = {r['id']: r for r in all_rows}
    examples = []
    for row in mine:
        if row['id'] not in clean_by_id:
            continue
        # A training prompt must never contain the target or future replies.
        context = preceding_safe_context(row, indexed)
        examples.append(dict(row, character='mugi', text=clean_by_id[row['id']]['text'],
                             context=context, evidence_type='style', reviewed=False))
    llm_source = ROOT / 'finetune_data/mugi/llm/source'
    write_jsonl(llm_source / 'dialogue_examples.jsonl', examples)
    summary = {'speaker': 'むぎ', 'slug': 'mugi', 'voice_prefix': 'vo1_', 'raw_dialogue': len(mine),
               'clean_dialogue': len(kept), 'filtered_dialogue': len(mine) - len(kept),
               'legacy_token_clean_dialogue': sum(is_usable(clean_text(r['text'])) for r in mine),
               'explicit_intimate_scene_label': 'H_Start (raw retained, training excluded)',
               'voiced_clean_dialogue': sum(bool(r['voice']) for r in kept),
               'archive_audio_files': len(entries), 'source_files': len({r['source_file'] for r in mine}),
               'parser_issues_total': len(issues), 'llm_source_records': len(examples),
               'llm_context_policy': 'only safe, same-segment preceding dialogue; no target/future lines',
               'missing_source_voice_ids': sorted({r['voice_id'] for r in mine if r['voice_id']
                                                and not (ROOT / 'extracted/voice' / (r['voice_id'] + '.opus')).is_file()}),
               'training_performed': False, 'api_calls': 0}
    (ROOT / 'finetune_data/mugi/source_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def prepare_tts():
    destination = ROOT / 'finetune_data/mugi/tts'
    # Rebuilding this new character may tighten filtering. Remove only obsolete,
    # previously generated Mugi WAVs, never any source audio or hika/ayame output.
    records = [json.loads(line) for line in
               (ROOT / 'extracted/characters/mugi/lines_clean.jsonl').read_text(encoding='utf-8').splitlines()]
    expected = {Path(row['voice']).stem for row in records if row.get('voice')}
    dataset = (destination / 'dataset/mugi').resolve()
    allowed = (ROOT / 'finetune_data/mugi/tts/dataset/mugi').resolve()
    if dataset != allowed or not dataset.is_relative_to(ROOT.resolve()):
        raise ValueError('Unexpected Mugi dataset boundary')
    for obsolete in dataset.glob('vo1_*.wav'):
        if obsolete.resolve().parent != allowed:
            raise ValueError('Unexpected generated audio boundary')
        if obsolete.stem not in expected:
            obsolete.unlink()
    subprocess.run([sys.executable, str(ROOT / 'finetune_data/tts/build_dataset.py'),
                    '--project-root', str(ROOT), '--out-dir', str(destination),
                    '--char', 'mugi=extracted/characters/mugi/lines_clean.jsonl'], cwd=ROOT, check=True)
    # The shared legacy builder generates an hika/ayame-specific README; replace only this new copy.
    (destination / 'README.md').write_text('''# 麦 GPT-SoVITS 数据集

此目录由原有 `finetune_data/tts/build_dataset.py` 生成，单独输出，未覆盖绯华或菖蒲。
`dataset/mugi/` 为 32 kHz、单声道、16-bit PCM；`mugi.list` 第三列为 `ja`。
时长限定 2–15 秒；`reference/mugi_ref_1..3.wav` 为 5–10 秒参考，配套 `.txt` 是日文原文。
详细数量、排除原因、时长和参考来源见 `qa_report.md`。

上传本目录后，将标注里的字面 `DATASET_ROOT` 替换为云端 `dataset` 的绝对路径。
例如：`sed -i 's|DATASET_ROOT|/root/GPT-SoVITS/data/mugi/tts/dataset|g' mugi.list`。
选择麦自己的标注单独训练；参考文本语种设 `ja`。尚未训练或验证中文跨语种音色。

重建：在项目根执行 `.venv/Scripts/python.exe scripts/prepare_mugi_training.py --skip-source`。
原始声音和训练音频仅留在本机。`seed_assets/mugi/voice_ref.opus` 保留原始 Opus 参考，
并与 `reference/mugi_ref_1.txt` 对应；未调用任何声音克隆服务。
''', encoding='utf-8')
    # Preserve an original Opus reference as for hika/ayame, rather than transcoding back from WAV.
    spec = importlib.util.spec_from_file_location('legacy_tts', ROOT / 'finetune_data/tts/build_dataset.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    passed = []
    for line in (destination / 'mugi.list').read_text(encoding='utf-8').splitlines():
        path, _, _, text = line.split('|', 3)
        wav = destination / path.replace('DATASET_ROOT/', 'dataset/')
        dur, rms, peak, _ = module.wav_info(wav)
        passed.append({'wav': wav, 'text': text, 'dur': dur, 'rms': rms, 'peak': peak, 'stem': wav.stem})
    # Manually reviewed everyday sentences, rather than low-RMS groans/sleep sounds.
    selected_stems = ('vo1_0002', 'vo1_0262', 'vo1_0032')
    by_stem = {p['stem']: p for p in passed}
    picked = [by_stem[stem] for stem in selected_stems]
    for i, p in enumerate(picked, 1):
        if not (5 <= p['dur'] <= 10 and p['rms'] >= 800 and p['peak'] < .98):
            raise ValueError('Manually selected reference no longer meets audio QA')
        reference = destination / 'reference' / f'mugi_ref_{i}.wav'
        shutil.copy2(p['wav'], reference)
        reference.with_suffix('.txt').write_text(p['text'], encoding='utf-8')
    report = (destination / 'qa_report.md').read_text(encoding='utf-8')
    report = '\n'.join(line for line in report.splitlines() if not line.startswith('  - reference/'))
    report += '\n\n## 人工文本审核后的日常参考音频\n\n'
    report += '自动音量排序可能选中非语言发声；最终参考已明确改选以下三句日常台词。\n'
    for i, p in enumerate(picked, 1):
        report += f'- reference/mugi_ref_{i}.wav ← {p["stem"]}.opus；{p["dur"]:.2f}s；RMS={p["rms"]:.0f}；peak={p["peak"]:.2f}；{p["text"]}\n'
    (destination / 'qa_report.md').write_text(report, encoding='utf-8')
    assets = ROOT / 'backend/seed_assets/mugi'
    assets.mkdir(parents=True, exist_ok=True)
    original = ROOT / 'extracted/voice' / f'{picked[0]["stem"]}.opus'
    shutil.copy2(original, assets / 'voice_ref.opus')
    (assets / 'voice_ref.txt').write_text(picked[0]['text'], encoding='utf-8')
    (assets / 'voice_ref.provenance.json').write_text(json.dumps({
        'source': original.relative_to(ROOT).as_posix(), 'reference_wav': 'mugi_ref_1.wav',
        'sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
        'duration_seconds': picked[0]['dur'], 'rms': picked[0]['rms'], 'peak_ratio': picked[0]['peak'],
        'is_cloned_voice': False}, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, default=ROOT / '国王恋爱')
    parser.add_argument('--source', type=Path, default=ROOT / 'extracted/scenario_all/scenario/main')
    parser.add_argument('--skip-source', action='store_true')
    parser.add_argument('--reuse-audio', action='store_true', help='逐一校验此前声音哈希并复用提取，不重新读取XP3索引')
    parser.add_argument('--skip-tts', action='store_true')
    parser.add_argument('--skip-llm', action='store_true')
    args = parser.parse_args()
    if not args.skip_source:
        prepare_sources(args.source, args.game_dir, args.reuse_audio)
    if not args.skip_tts:
        prepare_tts()
    if not args.skip_llm:
        subprocess.run([sys.executable, str(ROOT / 'finetune_data/mugi/build_llm.py')], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
