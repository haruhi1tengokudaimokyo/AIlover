"""Isolated Mugi LLM preparation; existing hika/ayame scripts/outputs are read-only.

Default: build Chinese card examples and convert any real translated records.
--translate: explicitly call the existing translation pipeline (requires API_KEY).
The default never accesses the network. Mock/kana/future-context records are rejected.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'llm/source/dialogue_examples.jsonl'
OUTPUT = HERE / 'llm/output'
KANA = re.compile(r'[぀-ゟ゠-ヿｦ-ﾟ]')


def legacy_module():
    spec = importlib.util.spec_from_file_location('legacy_sharegpt', ROOT / 'finetune_data/llm/build_sharegpt.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized_profile(profile):
    # Reuse the original card parser while retaining the explicit "Chinese adaptation" label.
    return re.sub(r'【中文改写示例([^】]*)】', r'【示例对话（中文改写）\1】', profile)


def validation_error(record, source):
    if not isinstance(record, dict):
        return 'invalid_record'
    if not isinstance(record.get('id'), str):
        return 'invalid_record_id'
    if record.get('mock') or record.get('qc_note') or record.get('qc_reason'):
        return 'mock_or_qc_placeholder'
    if not source or record.get('character') != 'mugi':
        return 'unknown_source_or_character'
    if record.get('text_src') != source['text'] or record.get('source_file') != source['source_file']:
        return 'source_mismatch'
    text = record.get('text_zh')
    if not isinstance(text, str) or not text.strip() or KANA.search(text) or text == source['text']:
        return 'target_not_translated_to_chinese'
    context = record.get('context_zh')
    if not isinstance(context, list) or any(not isinstance(item, dict) for item in context):
        return 'invalid_context'
    expected = [c['id'] for c in source.get('context', [])]
    if [c.get('id') for c in context] != expected:
        return 'context_ids_mismatch'
    for original, translated in zip(source.get('context', []), context):
        body = translated.get('text')
        if not isinstance(body, str) or not body.strip() or KANA.search(body):
            return 'context_not_translated_to_chinese'
        if translated.get('speaker') != original.get('speaker'):
            return 'context_speaker_mismatch'
    return None


def build_sources_glossary():
    data = json.loads((ROOT / 'finetune_data/llm/glossary.json').read_text(encoding='utf-8'))
    data['description'] = '麦的独立翻译词典；不改变原绯华、菖蒲词典。角色正式显示名统一为麦。'
    data['speaker_map']['むぎ'] = '麦'
    for entry in data['entries']:
        if entry['src'] == 'むぎ':
            entry.update(dst='麦', note='第一位女仆；也被旧卡称为小麦，这里统一为麦。')
        elif entry['src'] == 'ご主人様':
            entry.update(dst='主人', note='麦熟悉的称呼；语气自然亲近，不套用绯华的夸张敬语。')
    data['entries'].append({'src': 'むぎちゃん', 'dst': '麦酱', 'note': '麦偶尔给自己捧场时的自称，不要每句添加。'})
    path = HERE / 'llm/glossary.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def build(translated_path):
    module = legacy_module()
    card = json.loads((ROOT / 'backend/seed_cards/mugi.json').read_text(encoding='utf-8'))
    profile = normalized_profile(card['profile'])
    system = module.profile_to_system(profile, card['name'])
    seeds = [{'system': system, 'conversations': [{'from': 'human', 'value': user}, {'from': 'gpt', 'value': assistant}]}
             for user, assistant in module.parse_seed_examples(profile, card['name'])]
    errors = []
    if len(seeds) != 5 or not all(module.validate_sample(s, 'mugi_seed', errors) for s in seeds):
        raise ValueError('Expected five valid Chinese adaptation samples in Mugi card')
    originals = {row['id']: row for row in read_jsonl(SOURCE)}
    translations = read_jsonl(translated_path) if translated_path.is_file() else []
    samples, rejected, accepted_ids = [], Counter(), set()
    module.EMPTY_CONTEXT_OPENERS['mugi'] = '麦，陪我聊会儿吧。'
    for record in translations:
        ident = record.get('id') if isinstance(record, dict) else None
        reason = validation_error(record, originals.get(ident) if isinstance(ident, str) else None)
        if reason:
            rejected[reason] += 1
            continue
        if record['id'] in accepted_ids:
            rejected['duplicate_id'] += 1
            continue
        sample = module.record_to_sample(record, system)
        if not module.validate_sample(sample, 'mugi_corpus', errors):
            rejected['invalid_sharegpt'] += 1
            continue
        accepted_ids.add(record['id'])
        samples.append(sample)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Standard JSON arrays for direct LLaMA-Factory import, unlike legacy JSONL-with-.json suffix.
    for name, data in [('seed_samples.json', seeds), ('sharegpt.json', samples)]:
        (OUTPUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    def registration(file):
        return {'file_name': file, 'formatting': 'sharegpt',
                'columns': {'messages': 'conversations', 'system': 'system'},
                'tags': {'role_tag': 'from', 'content_tag': 'value', 'user_tag': 'human', 'assistant_tag': 'gpt'}}
    info = {'ousama_mugi_seed': registration('seed_samples.json')}
    if samples:
        info['ousama_mugi_corpus'] = registration('sharegpt.json')
    (OUTPUT / 'dataset_info.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    status = 'complete' if len(samples) == len(originals) else 'partial' if samples else 'not_started'
    summary = {'source_records': len(originals), 'chinese_adaptation_seed_samples': len(seeds),
               'accepted_real_translated_samples': len(samples), 'rejected_records': dict(rejected),
               'full_translation_status': status, 'seed_is_game_translation': False,
               'training_performed': False}
    (HERE / 'llm/build_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--translate', action='store_true', help='调用真实外部翻译 API；默认只离线构建')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--model')
    parser.add_argument('--translated-input', type=Path, default=OUTPUT / 'translated.jsonl')
    args = parser.parse_args()
    glossary = build_sources_glossary()
    if args.translate:
        if args.translated_input.resolve() != (OUTPUT / 'translated.jsonl').resolve():
            parser.error('--translated-input 仅用于离线导入；翻译写入固定独立目录')
        command = [sys.executable, str(ROOT / 'finetune_data/llm/translate_corpus.py'),
                   '--input', str(SOURCE), '--output', str(OUTPUT / 'translated.jsonl'),
                   '--qc-failed', str(OUTPUT / 'qc_failed.jsonl'), '--glossary', str(glossary),
                   '--workers', str(args.workers)]
        if args.limit is not None:
            command.extend(['--limit', str(args.limit)])
        if args.model:
            command.extend(['--model', args.model])
        subprocess.run(command, cwd=ROOT, check=True)
    build(args.translated_input)


if __name__ == '__main__':
    main()
