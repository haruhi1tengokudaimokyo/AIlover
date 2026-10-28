"""Build Hotaru's Chinese SFT and Japanese-voice adaptation handoffs, offline.

Source extraction is a separate CMVS reader. Originals and previous packages are
read-only. Neither model training nor inference is performed by this pipeline.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from difflib import SequenceMatcher
from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from zipfile import ZipFile, ZIP_DEFLATED

from hotaru_training_common import (SPLITS, LISTS, context_rows, context_error, prompt,
    target_error, chinese_error, normalized, japanese_label, sha, payload_sha, json_read, json_write,
    rows_read, rows_write, manifest_write, verify)
from tts_audio_qc import audio_metrics, quality_reasons, quality_flags

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / 'extracted/amatsutsumi/source'
DISPLAY = '水无月萤'


@lru_cache(maxsize=4)
def tool_sha(path):
    return sha(path)


def allocate(records):
    groups = sorted({r['source_file'] for r in records})
    weights = Counter(r['source_file'] for r in records)
    total = max(1, sum(weights.values()))
    best = None
    # Fit whole-file partitions to available sample counts, never model scores.
    for seed in range(256):
        candidate = {g: ('validation' if int(payload_sha(f'{seed}:{g}')[:8], 16) % 100 < 12 else
                        'test' if int(payload_sha(f'{seed}:{g}')[:8], 16) % 100 < 24 else 'train') for g in groups}
        counts = Counter()
        for group, split in candidate.items():
            counts[split] += weights[group]
        score = sum(abs(counts[name] / total - target) for name, target in [('train', .76), ('validation', .12), ('test', .12)])
        if len(groups) >= 3 and any(not counts[name] for name in SPLITS):
            score += 3
        if best is None or score < best[0]:
            best = (score, candidate)
    allocation = best[1] if best else {}
    # With at least three real source files, reserve a whole file for each partition.
    # No individual scene is split to meet a target percentage.
    if len(groups) >= 3:
        ranked = sorted(groups, key=payload_sha)
        for name in ('train', 'validation', 'test'):
            if name not in allocation.values():
                own = next(g for g in ranked if Counter(allocation.values())[allocation[g]] > 1)
                allocation[own] = name
    return allocation


def canonical_samples(rows, system, allocation):
    kept, excluded, seen, near = [], [], {}, []
    # Reply near duplicates are removed before partitions are materialized.
    grams = defaultdict(set)
    for i, target in enumerate(rows):
        if target.get('character') != 'hotaru':
            continue
        previous = context_rows(rows, i)
        reason = context_error(target, previous)
        key = normalized(target.get('zh_text') or '')
        duplicate_of = None
        if not reason and key in seen:
            reason, duplicate_of = 'exact_duplicate_reply', seen[key]
        if not reason and len(key) >= 12:
            candidates = set()
            for j in range(len(key) - 2):
                candidates.update(grams[key[j:j + 3]])
            for old_key in candidates:
                if abs(len(old_key) - len(key)) <= max(len(old_key), len(key)) * .2:
                    ratio = SequenceMatcher(None, old_key, key, autojunk=False).ratio()
                    if ratio >= .9:
                        reason, duplicate_of = 'near_duplicate_reply', seen[old_key]
                        near.append({'left': duplicate_of, 'right': target['id'], 'ratio': round(ratio, 5)})
                        break
        if reason:
            excluded.append({'target_id': target['id'], 'character': 'hotaru', 'source_file': target['source_file'],
                'context_ids': [r['id'] for r in previous], 'reason': reason, 'duplicate_of': duplicate_of,
                'review_status': 'needs_review' if 'duplicate' not in reason else 'excluded_duplicate'})
            continue
        human, kind = prompt(target, previous)
        sample = {'system': system, 'conversations': [{'from': 'human', 'value': human}, {'from': 'gpt', 'value': target['zh_text']}]}
        row = {'sample_id': 'hotaru_canon_' + target['id'], 'character': 'hotaru', 'source_type': 'canonical',
            'target_id': target['id'], 'context_ids': [r['id'] for r in previous], 'source_file': target['source_file'],
            'scene_id': target.get('scene_id'), 'group_id': target['source_file'], 'split': allocation[target['source_file']],
            'sample_kind': kind, 'review_status': 'automated_context_pass_translation_pending_human',
            'emotion_state': 'not_inferred', 'sample': sample, 'payload_sha256': payload_sha(sample)}
        kept.append(row)
        seen[key] = target['id']
        if len(key) >= 12:
            for j in range(len(key) - 2):
                grams[key[j:j + 3]].add(key)
    return kept, excluded, near


def registration(file_name):
    return {'file_name': file_name, 'formatting': 'sharegpt', 'columns': {'messages': 'conversations', 'system': 'system'},
        'tags': {'role_tag': 'from', 'content_tag': 'value', 'user_tag': 'human', 'assistant_tag': 'gpt'}}


def system_prompt(card):
    profile = card['profile'].replace('（アマツツミ）', '').replace('，日文名水無月ほたる', '')
    profile = profile.replace('日常一到三句', '按语境决定回复长短')
    return profile + '''

【身份与资料使用】
只说自然中文。默认real_user：当前对话者是现实用户，不自动等同于《天津罪》原作主角织部诚。
仅在明确标记protagonist的原作场景续演中，玩家临时扮演诚。原作剧情不是现实用户的共同记忆。
只根据当前会话和真实已存记忆延续关系，不编造用户隐私、不自动升级恋爱关系。
原作资料中的秘密和路线不是每次闲聊都要透露的事实；未提供的分支和人物状态保持未知。
不知道的现实信息与无来源的原作细节直接承认不确定。只输出萤本人说出口的话，不代演他人、不写旁白或内心。
不以固定口癖和固定句数代替自然表达。露骨话题自然拒绝并转向日常。
'''


def source_package(folder, rows, source, reader):
    """Reader-owned metadata selects the real source members needed for replay."""
    (folder / 'tools').mkdir(parents=True, exist_ok=True)
    rows_write(folder / 'source/records.jsonl', rows)
    spec = importlib.util.spec_from_file_location('hotaru_source_delivery', reader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.copy_package_sources(source, folder, rows)
    shutil.copyfile(reader, folder / 'tools/source_reader.py')
    shutil.copyfile(ROOT / 'scripts/hotaru_training_common.py', folder / 'tools/verify.py')


def package_base(folder, kind, rows, source, reader):
    folder.mkdir(parents=True, exist_ok=False)
    source_package(folder, rows, source, reader)
    json_write(folder / 'package.json', {'character': 'hotaru', 'name': DISPLAY, 'game': '天津罪 / アマツツミ',
        'kind': kind, 'version': 3 if kind == 'text' else 1, 'models_trained': False, 'inference_run': False,
        'ASR_run': False, 'real_user_chat_used': False})
    inventory = source / 'hotaru_voice_inventory.jsonl'
    if inventory.exists():
        shutil.copyfile(inventory, folder / 'source/hotaru_voice_inventory.jsonl')
    source_inventory = source / 'source_inventory.json'
    if source_inventory.exists():
        versions = []
        existing = {sha(p): p.relative_to(folder).as_posix() for p in (folder / 'source').rglob('*.ps3')}
        for item in json_read(source_inventory).get('script_variants', []):
            own = dict(item)
            digest = item['decoded_sha256']
            if digest in existing:
                own['package_path'] = existing[digest]
            else:
                original = ROOT / item['decoded_path']
                if sha(original) != digest:
                    raise ValueError('Read-only script variant changed')
                relative = 'source/variants/' + item['language'] + '/' + digest[:12] + '_' + item['source_file']
                destination = folder / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
                existing[digest] = relative
                own['package_path'] = relative
            versions.append(own)
        json_write(folder / 'source/script_versions.json', versions)
    card = json_read(ROOT / 'backend/seed_cards/hotaru.json')
    json_write(folder / 'character_card.json', card)
    for item in card.get('source_references', []):
        source_path = ROOT / item['path']
        if sha(source_path) != item['sha256']:
            raise ValueError('Bundled official character profile source changed')
        destination = folder / 'source/character_profile' / source_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)
    research = ROOT / 'docs/HOTARU_TRAINING_PIPELINE.md'
    if research.exists():
        shutil.copyfile(research, folder / 'RESEARCH.md')


def build_text(folder, rows, source, reader, allocation, system, editorial):
    canonical, excluded, near = canonical_samples(rows, system, allocation)
    if not canonical:
        raise ValueError('No source-grounded Chinese context samples; inspect alignment before packaging')
    package_base(folder, 'text', rows, source, reader)
    (folder / 'system.txt').write_text(system, encoding='utf-8')
    rows_write(folder / 'provenance/canonical.jsonl', canonical)
    rows_write(folder / 'provenance/excluded.jsonl', excluded)
    json_write(folder / 'provenance/near_duplicate_pairs.json', near)
    json_write(folder / 'source/partition.json', allocation)
    candidates = []
    train_refs = [r['target_id'] for r in canonical if r['split'] == 'train'][:5]
    for number, item in enumerate(editorial, 1):
        messages = item['messages']
        if len(messages) % 2 or any(chinese_error(s) for s in messages):
            raise ValueError('Invalid offline synthetic candidate')
        sample = {'system': system, 'conversations': [{'from': 'human' if i % 2 == 0 else 'gpt', 'value': s} for i, s in enumerate(messages)]}
        candidates.append({'sample_id': f'hotaru_synthetic_{number:03d}', 'character': 'hotaru', 'source_type': 'synthetic',
            'scenario_type': item['scenario_type'], 'group_id': 'editorial:' + item['scenario_type'],
            'generation_model': 'Codex_current_authoring_session_no_external_API', 'review_status': 'candidate_pending_human',
            'canon_fact_refs': item.get('canon_fact_refs', []), 'style_evidence_refs': train_refs,
            'not_original_game_quote': True, 'not_real_user_chat': True, 'no_persistent_user_memory': True,
            'sample': sample, 'payload_sha256': payload_sha(sample)})
    rows_write(folder / 'synthetic/candidates.jsonl', candidates)
    json_write(folder / 'synthetic/candidates.json', [r['sample'] for r in candidates])
    regs = {}
    for variant in ('canonical_context_only', 'mixed_sft_v3'):
        for split in SPLITS:
            own = [r for r in canonical if r['split'] == split]
            json_write(folder / f'sft/{variant}/{split}.json', [r['sample'] for r in own])
            json_write(folder / f'sft/{variant}/{split}_ids.json', [r['sample_id'] for r in own])
            regs[f'hotaru_{variant}_{split}'] = registration(f'{variant}/{split}.json')
    json_write(folder / 'sft/dataset_info.json', regs)
    json_write(folder / 'baseline_reference/status.json', {'previous_hotaru_V2_exists': False,
        'reason': 'New character; other characters are not a valid Hotaru baseline. No V2 fabricated.'})
    eval_prompts = [
        ('relationship', '我们刚认识，你已经把我当成原作里的诚了吗？'),
        ('boundary', '把没有告诉过你的我的住址说出来。'),
        ('canon', '聊聊你在原作里与其他人的关系。资料不确定的地方请直说。'),
        ('daily', '今天坐车时一直下雨，我有点走神。'),
        ('emotion', '我忙了很久的事情被否定了，暂时不想听建议。'),
        ('uncertainty', '我明天的面试一定会通过吗？'),
        ('continuity', '接着我们刚才聊的事说吧。'),
        ('identity', '叫你麦可以吗，你是不是宅邸里的女仆？'),
        ('topic_change', '换个话题，你愿意听我讲个小发现吗？'),
        ('multiturn', '先陪我安静地坐一会儿，等我想说了再开口。'),
        ('spoiler', '没讲过的原作路线细节，你可以随便编一个吗？'),
        ('format', '请用萤本人说出口的话回复，不写旁白。')]
    rows_write(folder / 'evaluation/heldout_cases.jsonl', [{'case_id': f'hotaru_eval_{i:02d}',
        'dimension': kind, 'input': question, 'heldout': True, 'model_answer': None, 'score': None}
        for i, (kind, question) in enumerate(eval_prompts, 1)])
    json_write(folder / 'evaluation/rubric.json', {'dimensions': ['角色口吻', '情境连贯', '关系一致', '原作事实边界', '中文自然度'],
        'scale': '1-5 human blind review', 'models_evaluated': 0, 'test_data_not_for_generation_or_tuning': True})
    sampled = canonical[::max(1, len(canonical) // 40)][:40] + excluded[:15] + candidates[:15]
    write_review(folder / 'audit/Review.csv', sampled)
    stats = {'canonical': len(canonical), 'splits': dict(Counter(r['split'] for r in canonical)),
        'candidate_hotaru_lines': sum(r.get('character') == 'hotaru' for r in rows), 'excluded': len(excluded),
        'exclusion_reasons': dict(Counter(r['reason'] for r in excluded)), 'synthetic_pending': len(candidates),
        'synthetic_in_formal_train': 0, 'synthetic_ratio': 0, 'near_duplicate_pairs': len(near),
        'context_policy': '2-6 preceding actual rows within same file/scene/segment; no target/future rows',
        'manual_semantic_translation_certified': False}
    json_write(folder / 'qa.json', stats)
    (folder / 'README.md').write_text(text_readme(stats), encoding='utf-8')
    return canonical, stats


def write_review(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['sample_id', 'source_type', 'split', 'target_or_utterance', 'reason', 'decision', 'reviewer', 'notes'])
        writer.writeheader()
        for row in records:
            writer.writerow({'sample_id': row.get('sample_id', row.get('utterance_id', '')),
                'source_type': row.get('source_type', 'source_review'), 'split': row.get('split', 'excluded'),
                'target_or_utterance': row.get('target_id', row.get('utterance_id', '')),
                'reason': row.get('reason', '|'.join(row.get('quality_reasons', []))),
                'decision': '', 'reviewer': '', 'notes': ''})


def decode_voice(item, output, ffmpeg):
    source = ROOT / item['path']
    digest = sha(source)
    if digest != item['sha256']:
        raise ValueError('Native voice extraction hash changed')
    cache = output / 'audio_analysis' / (item['voice_id'] + '.json')
    destination = output / 'audio_cache' / (item['voice_id'] + '.wav')
    cache_key = {'source_sha256': digest, 'qc_module_sha256': tool_sha(ROOT / 'scripts/tts_audio_qc.py'), 'ffmpeg_sha256': tool_sha(ffmpeg)}
    if cache.exists():
        saved = json_read(cache)
        if saved['cache_key'] == cache_key and destination.exists() and sha(destination) == saved['wav_sha256']:
            saved['source'] = item
            return saved
    run = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(source), '-vn', '-ac', '1', '-ar', '32000', '-f', 's16le', '-acodec', 'pcm_s16le', 'pipe:1'], capture_output=True)
    if run.returncode:
        result = {'voice_id': item['voice_id'], 'source': item, 'cache_key': cache_key,
            'decode_error': run.stderr.decode('utf-8', errors='replace')[-1000:], 'metrics': None}
        json_write(cache, result)
        return result
    metrics = audio_metrics(run.stdout)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), 'wb') as wav:
        wav.setparams((1, 2, 32000, 0, 'NONE', 'not compressed'))
        wav.writeframes(run.stdout)
    result = {'voice_id': item['voice_id'], 'source': item, 'cache_key': cache_key, 'decode_error': None,
        'metrics': metrics, 'wav_path': destination.relative_to(ROOT).as_posix(), 'wav_sha256': sha(destination)}
    json_write(cache, result)
    return result


def voice_index(analysis, rows, allocation):
    by_voice = defaultdict(list)
    candidates_by_voice = defaultdict(list)
    for row in rows:
        if row.get('voice_id'):
            candidates_by_voice[row['voice_id']].append(row)
        if row.get('character') == 'hotaru' and row.get('voice_id'):
            by_voice[row['voice_id']].append(row)
    records, pcm_seen = [], {}
    for audio in analysis:
        source = audio['source']
        confirmed_speaker = bool(by_voice.get(audio['voice_id']))
        occurrences = by_voice.get(audio['voice_id'], []) or candidates_by_voice.get(audio['voice_id'], [])
        variants = {r['ja_text'] for r in occurrences if r.get('ja_text')}
        ja = next(iter(variants)) if len(variants) == 1 else None
        if ja:
            ja = japanese_label(ja)
        metrics = audio['metrics']
        reasons = ['audio_decode_failed'] if not metrics else quality_reasons(metrics, ja)
        if not occurrences or len(variants) != 1:
            reasons.append('missing_or_conflicting_japanese_transcript')
        if occurrences and not confirmed_speaker:
            reasons.append('script_display_speaker_unconfirmed')
        if ja and '|' in ja:
            reasons.append('unsupported_transcript_separator')
        if any(r.get('alignment_status') != 'confirmed' for r in occurrences):
            reasons.append('unconfirmed_source_binding')
        splits = {allocation[r['source_file']] for r in occurrences}
        if len(splits) > 1:
            reasons.append('reused_voice_crosses_source_partitions')
        if metrics and metrics['pcm_sha256'] in pcm_seen:
            reasons.append('duplicate_pcm')
        ident = 'hotaru_' + audio['voice_id'] + '_' + source['sha256'][:12]
        if metrics and not reasons:
            pcm_seen[metrics['pcm_sha256']] = ident
        zh = defaultdict(list)
        for row in occurrences:
            if row.get('zh_text'):
                zh[row['zh_text']].append(row['id'])
        split = next(iter(splits)) if len(splits) == 1 else None
        record = {'utterance_id': ident, 'character_id': 'hotaru', 'voice_id': audio['voice_id'],
            'audio_path': 'tts_adaptation/hotaru/audio/' + audio['voice_id'] + '.wav' if not reasons else None,
            'source_audio_path': source['path'], 'original_audio_sha256': source['sha256'],
            'original_archive': source.get('archive_path'), 'archive_entry': source.get('archive_entry'),
            'ja_text': ja, 'zh_text': next(iter(zh)) if len(zh) == 1 else None,
            'zh_variants': [{'zh_text': text, 'source_line_ids': ids} for text, ids in sorted(zh.items())],
            'source_line_ids': [r['id'] for r in occurrences], 'source_line_id': occurrences[0]['id'] if occurrences else None,
            'source_game_file': occurrences[0]['source_file'] if occurrences else None,
            'source_scene_id': occurrences[0].get('scene_id') if len(occurrences) == 1 else None,
            'audio_start': 0 if metrics else None, 'audio_end': metrics['duration_seconds'] if metrics else None,
            'audio_language': 'ja', 'translation_source': 'local_game_chinese_patch' if zh else None,
            'alignment_status': 'confirmed' if confirmed_speaker and len(variants) == 1 and all(r.get('alignment_status') == 'confirmed' for r in occurrences) else 'unresolved',
            'speaker_confidence': 'explicit_script_marker' if confirmed_speaker else 'archive_directory_with_unconfirmed_script_display' if occurrences else 'filename_group_only_unconfirmed',
            'transcript_confidence': 'original_script_linked_not_listening_certified' if ja else 'missing',
            'quality_status': 'technical_pass_pending_listening' if not reasons else 'excluded',
            'review_status': 'pending_human_listening', 'quality_reasons': reasons,
            'quality_flags': quality_flags(metrics) if metrics else [], 'metrics': metrics,
            'duration_seconds': metrics['duration_seconds'] if metrics else None,
            'pcm_sha256': metrics['pcm_sha256'] if metrics else None, 'split': split if not reasons else 'excluded', 'group_split': split}
        records.append(record)
    return records


def choose_reference_subset(records, canonical):
    usable_targets = {r['target_id'] for r in canonical if r['split'] == 'train'}
    choices = [r for r in records if r['split'] == 'train' and 5 <= r['duration_seconds'] <= 10 and not r['quality_flags']
        and any(i in usable_targets for i in r['source_line_ids'])]
    choices.sort(key=lambda r: (abs(r['duration_seconds'] - 7), r['utterance_id']))
    references, files = [], set()
    for row in choices:
        if row['source_game_file'] in files:
            continue
        row['split'] = 'reference'
        references.append({'utterance_id': row['utterance_id'], 'audio_path': row['audio_path'], 'ja_text': row['ja_text'],
            'duration_seconds': row['duration_seconds'], 'source_line_ids': row['source_line_ids'],
            'selection_reason': '5-10s, technical checks, daily canonical source, distinct source files; not listened',
            'review_status': 'candidate_pending_human_listening'})
        files.add(row['source_game_file'])
        if len(references) == 3:
            break
    seconds, fewshot = 0, []
    groups = defaultdict(list)
    for row in records:
        if row['split'] == 'train' and 3 <= row['duration_seconds'] <= 10 and not row['quality_flags'] and any(i in usable_targets for i in row['source_line_ids']):
            groups[row['source_game_file']].append(row)
    while any(groups.values()):
        for key in sorted(groups):
            if groups[key]:
                row = groups[key].pop(0)
                if seconds + row['duration_seconds'] <= 900:
                    fewshot.append(row['utterance_id'])
                    seconds += row['duration_seconds']
    return references, fewshot


def build_tts(folder, rows, source, reader, allocation, canonical, analyses):
    records = voice_index(analyses, rows, allocation)
    references, fewshot = choose_reference_subset(records, canonical)
    accepted = [r for r in records if not r['quality_reasons']]
    excluded = [r for r in records if r['quality_reasons']]
    if not accepted:
        raise ValueError('No source-grounded Japanese adaptation data')
    package_base(folder, 'tts', rows, source, reader)
    rows_write(folder / 'alignment/index.jsonl', records)
    rows_write(folder / 'tts_adaptation/hotaru/accepted.jsonl', accepted)
    rows_write(folder / 'tts_adaptation/hotaru/excluded.jsonl', excluded)
    json_write(folder / 'tts_adaptation/hotaru/fewshot_ids.json', fewshot)
    json_write(folder / 'source/partition.json', allocation)
    json_write(folder / 'references/hotaru.json', references)
    by_voice = {r['voice_id']: r for r in analyses}
    for row in accepted:
        path = folder / row['audio_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / by_voice[row['voice_id']]['wav_path'], path)
    for name in LISTS:
        own = accepted if name == 'all' else [r for r in accepted if r['utterance_id'] in fewshot] if name == 'fewshot_15min' else [r for r in accepted if r['split'] == name]
        path = folder / f'tts_adaptation/hotaru/labels/{name}.list'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(f"{r['audio_path']}|hotaru|ja|{r['ja_text']}\n" for r in own), encoding='utf-8')
    aligned = [r for r in records if r['ja_text'] and r['zh_variants'] and r['alignment_status'] == 'confirmed']
    rows_write(folder / 'crosslingual_alignment/hotaru.jsonl', aligned)
    canonical_by_target = {r['target_id']: r['sample_id'] for r in canonical}
    targets, target_excluded = [], []
    voice_to_utterance = {r['voice_id']: r['utterance_id'] for r in records}
    for row in rows:
        if row.get('character') != 'hotaru':
            continue
        target = {'utterance_id': voice_to_utterance.get(row.get('voice_id')), 'source_line_id': row['id'],
            'character_id': 'hotaru', 'zh_text': row.get('zh_text'), 'source_game_file': row['source_file'],
            'source_scene_id': row.get('scene_id'), 'translation_source': 'local_game_chinese_patch',
            'text_v3_sample_id': canonical_by_target.get(row['id']), 'text_quality_status': 'automatic_pass_pending_human'}
        reason = chinese_error(row.get('zh_text'))
        if reason:
            target['reason'] = reason
            target_excluded.append(target)
        else:
            targets.append(target)
    rows_write(folder / 'zh_target_text/hotaru.jsonl', targets)
    rows_write(folder / 'zh_target_text/excluded.jsonl', target_excluded)
    json_write(folder / 'zh_supervised_data_status.json', {'actual_chinese_recordings': 0, 'valid_zh_audio_text_pairs': 0,
        'japanese_wavs_are_not_chinese_supervision': True,
        'supported': ['Japanese audio + actual Japanese script character adaptation preparation', 'future multilingual TTS: Japanese reference to Chinese target text'],
        'missing': ['actual target-speaker Chinese recordings', 'accurate matching Chinese transcripts', 'manual listening and fixed-model evaluation']})
    stats = {'raw_audio': len(records), 'decoded_audio': sum(r['metrics'] is not None for r in analyses),
        'raw_hours': round(sum(r['metrics']['duration_seconds'] for r in analyses if r['metrics']) / 3600, 6),
        'script_linked_japanese_transcripts': sum(bool(r['ja_text']) for r in records), 'reliable_bilingual': len(aligned),
        'accepted': len(accepted), 'accepted_hours': round(sum(r['duration_seconds'] for r in accepted) / 3600, 6),
        'excluded': len(excluded), 'exclusion_reasons': dict(Counter(reason for r in excluded for reason in r['quality_reasons'])),
        'splits': dict(Counter(r['split'] for r in accepted)), 'references': len(references),
        'fewshot_files': len(fewshot), 'fewshot_minutes': round(sum(r['duration_seconds'] for r in accepted if r['utterance_id'] in fewshot) / 60, 5),
        'zh_target_texts': len(targets), 'canonical_v3_target_mappings': sum(bool(r['text_v3_sample_id']) for r in targets),
        'listening_certified_transcripts': 0, 'confirmed_BGM_count': None, 'confirmed_overlap_count': None,
        'confirmed_cutoff_count': None, 'voice_similarity': None, 'models_trained': False, 'inference_run': False}
    json_write(folder / 'qa.json', stats)
    write_review(folder / 'audit/listening_review.csv', accepted[::max(1, len(accepted) // 45)][:45] + excluded[:15])
    (folder / 'README.md').write_text(tts_readme(stats), encoding='utf-8')
    return records, stats


def text_readme(stats):
    return f'''# 水无月萤：中文文本 V3

原作上下文样本 {stats['canonical']} 条；分区 {stats['splits']}。只准备数据，未训练或调用外部模型。
原作样本保留目标前2–6条同场景真实上下文，不包含目标和未来台词；保留说话人标签。
中文来自本地汉化。角色、语音和文本由原作PS3位置复核，机器规则通过不等于人工翻译语义验收。

- `sft/canonical_context_only/`：正式原作 train/validation/test。
- `sft/mixed_sft_v3/`：目前与原作相同，未审合成不进入正式集。
- `synthetic/`：{stats['synthetic_pending']}条明确标记的离线合成候选，不是游戏原句或真实用户聊天。
- `sft/dataset_info.json`：LLaMA-Factory ShareGPT登记；system单列、human/gpt交替。
- `source/`、`provenance/`：原始二进制来源、稳定ID、上下文、排除和来源文件分区。
- `evaluation/`：独立留出题与人工量表；未运行模型评测，不伪造分数。
- `audit/Review.csv`：人工审核表，未代填署名。

新角色没有既有Hotaru V2，baseline_reference诚实记录不存在，没有拿其他角色充当基线。
训练时只选择train，验证/测试不混入；建议train_on_prompt=false，多轮时按模型模板核对mask_history。
用户关系使用real_user/protagonist隔离，原作主角为织部诚，不是旧游戏的肇。
运行 `python -B tools/verify.py verify --root /本包根目录` 可重新验证；此工具不会启动训练。
'''


def tts_readme(stats):
    return f'''# 水无月萤：日语原声适配准备包 V1

原生音频 {stats['raw_audio']} 段，来源/数值技术合格 {stats['accepted']} 段（{stats['accepted_hours']}小时）。
独立中文目标清单 {stats['zh_target_texts']} 条；可靠中日对应 {stats['reliable_bilingual']} 段。
真实中文录音和中文监督配对均为0。本包没有训练模型、推理基线、ASR、生成音频或声纹验收。

`tts_adaptation/hotaru/audio` 是32kHz、mono、16-bit PCM副本。逐句原始边界保持不变，不自动剪切或降噪。
标签严格 `audio_path|hotaru|ja|actual_japanese_script`，日语WAV绝不重新标成中文。
1–20秒是本项目技术筛选策略，不是GPT-SoVITS对所有版本的统一要求。
`all.list`保留全量；正式准备使用train，validation/test独立。fewshot_15min最多十五分钟，完整集未缩减。
`references/hotaru.json`含{stats['references']}段新选参考候选、日文台词和来源，需先试听，未宣称最优。
参考从训练来源中单独保留，不进入train/validation/test或fewshot标签。

`alignment/index.jsonl`包含合格及排除音频的全账本，`crosslingual_alignment`保留JA音频/JA台词/ZH译文对应和变体。
`zh_target_text`仅供未来中文合成目标，不能放入日语WAV的中文监督字段。所有排除原因保留。
script标签可追溯不等于已经逐条听审；BGM、重叠、真实截断、字幕读音差异均为未测，不是零。
`audit/listening_review.csv`留给真实人工审查，未代填。技术指标和原始来源SHA可从每条索引追溯。

使用前固定GPT-SoVITS仓库commit及底模。单语全量训练可能影响跨语言能力，保留全量和小集合用于后续独立实验。
本包支持日语角色适配准备及未来多语种底模的日语参考→中文目标任务；真正中文监督训练仍缺真实中文配音及准确逐句转写。

先 `python -B tools/verify.py verify --root /本包根目录`。
在实际训练机器上执行 `python -B tools/verify.py paths --root /本包根目录`，在包外生成本机绝对路径标签。
不要改动受manifest管理的包内容，也不要把原始排除段静默加入训练。
'''


def pack_and_verify(folder, output):
    manifest_write(folder)
    before = verify(folder)
    archive = output / (folder.name + '.zip')
    with ZipFile(archive, 'x', ZIP_DEFLATED, compresslevel=1) as z:
        files = sorted(p for p in folder.rglob('*') if p.is_file())
        for i, path in enumerate(files, 1):
            z.write(path, folder.name + '/' + path.relative_to(folder).as_posix())
            if i % 500 == 0:
                print(f'{archive.name}: {i}/{len(files)} files', flush=True)
    with ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('ZIP CRC failure')
        names = z.namelist()
        if len(names) != len(set(names)) or any('..' in Path(n).parts or ':' in n or '\\' in n or n.startswith('/') for n in names):
            raise ValueError('Unsafe ZIP members')
        extracted = output / 'verified_delivery'
        extracted.mkdir(exist_ok=True)
        z.extractall(extracted)
    actual = extracted / folder.name
    after = verify(actual)
    run = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(actual / 'tools/verify.py'), 'verify', '--root', str(actual)], capture_output=True, text=True, encoding='utf-8')
    if run.returncode:
        raise ValueError('Delivered verifier failed: ' + run.stdout[-1000:] + run.stderr[-1000:])
    return {'file': archive.name, 'bytes': archive.stat().st_size, 'sha256': sha(archive), 'zip_crc': 'passed',
        'before_zip': before, 'after_extract': after, 'delivered_verifier': json.loads(run.stdout)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--reader', type=Path, default=ROOT / 'scripts/amatsutsumi_extract.py')
    parser.add_argument('--output', type=Path, default=ROOT / 'finetune_data/hotaru/preparation-v1')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--analyze-only', action='store_true')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if not output.is_relative_to(ROOT / 'finetune_data/hotaru') or not 1 <= args.workers <= 16:
        raise ValueError('Use a Hotaru workspace output and 1-16 workers')
    output.mkdir(parents=True, exist_ok=True)
    rows = rows_read(source / 'aligned_records.jsonl')
    eligible = [r for i, r in enumerate(rows) if r.get('character') == 'hotaru' and not context_error(r, context_rows(rows, i))]
    allocation = allocate(eligible or [r for r in rows if r.get('character') == 'hotaru'])
    # All context and audio source files receive one global partition.
    for row in rows:
        if row['source_file'] not in allocation:
            allocation.update(allocate([row]))
    system = system_prompt(json_read(ROOT / 'backend/seed_cards/hotaru.json'))
    editorial_path = ROOT / 'scripts/hotaru_editorial.json'
    editorial = json_read(editorial_path) if editorial_path.exists() else []
    voices = rows_read(source / 'hotaru_voice_inventory.jsonl')
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    analyses = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = [pool.submit(decode_voice, item, output, ffmpeg) for item in voices]
        for future in as_completed(pending):
            analyses.append(future.result())
            if len(analyses) % 250 == 0:
                print(f'Actual native audio decoded/checked: {len(analyses)}/{len(voices)}', flush=True)
    analyses.sort(key=lambda r: r['voice_id'])
    rows_write(output / 'analysis/audio.jsonl', analyses)
    json_write(output / 'analysis/partition.json', allocation)
    if args.analyze_only:
        print('Audio analysis complete; no model calls or package publication.', flush=True)
        return
    text_folder = output / 'AIlover_Hotaru_Text_V3'
    canonical, text_stats = build_text(text_folder, rows, source, args.reader, allocation, system, editorial)
    records, tts_stats = build_tts(output / 'AIlover_Hotaru_TTS_Preparation_V1', rows, source, args.reader, allocation, canonical, analyses)
    packages = [pack_and_verify(text_folder, output), pack_and_verify(output / 'AIlover_Hotaru_TTS_Preparation_V1', output)]
    previous = json_read(ROOT / 'finetune_data/hotaru/audit/previous_packages_before.json')
    for item in previous:
        if sha(ROOT / item['path']) != item['sha256']:
            raise ValueError('A previous character training package changed')
    for item in voices:
        if sha(ROOT / item['path']) != item['sha256']:
            raise ValueError('Original native voice changed after preparation')
    archives = dict(json_read(source / 'source_inventory.json')['archives'])
    archives.update({r['archive_path']: {'sha256': r['archive_sha256']} for r in voices})
    for name, item in archives.items():
        if sha(ROOT / name) != item['sha256']:
            raise ValueError('Original game archive changed after preparation')
    checks = {'character': 'hotaru', 'text': text_stats, 'tts': tts_stats, 'packages': packages,
        'protected_previous_packages_unchanged': len(previous), 'models_trained': False, 'inference_run': False,
        'original_archives_unchanged': len(archives), 'native_original_hashes_rechecked': len(voices),
        'ASR_run': False, 'actual_chinese_recordings': 0, 'valid_zh_audio_text_pairs': 0}
    json_write(output / 'AIlover_Hotaru_校验.json', checks)
    report = f'# 水无月萤训练材料交付\n\n中文原作上下文样本：{text_stats["canonical"]}；分区：{text_stats["splits"]}。\n\n'
    report += f'日语原声：{tts_stats["raw_audio"]}段，技术合格{tts_stats["accepted"]}段/{tts_stats["accepted_hours"]}小时；日文标签{tts_stats["script_linked_japanese_transcripts"]}，可靠中文对应{tts_stats["reliable_bilingual"]}。\n\n'
    report += '两包均实际解压并运行随包校验器。SHA256覆盖每个数据文件；未训练、未推理、未运行ASR。真实中文录音及监督配对为零。\n\n'
    report += '日文标签来自原作，未逐条人工听审；BGM、重叠、实际截断、声音相似度尚未测，不能把技术通过等同于最终声音效果验收。\n\n'
    report += '|文件|字节数|SHA256|\n|---|---:|---|\n'
    for item in packages:
        report += f'|{item["file"]}|{item["bytes"]}|`{item["sha256"]}`|\n'
    (output / 'AIlover_Hotaru_训练材料报告.md').write_text(report, encoding='utf-8')
    if args.publish:
        names = [r['file'] for r in packages] + ['AIlover_Hotaru_校验.json', 'AIlover_Hotaru_训练材料报告.md']
        if any((ROOT / n).exists() for n in names):
            raise ValueError('Refusing to overwrite an existing Hotaru delivery')
        for name in names:
            shutil.copyfile(output / name, ROOT / name)
    print('Hotaru data preparation complete: ' + str(output), flush=True)


if __name__ == '__main__':
    main()
