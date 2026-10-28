"""Full native Japanese voice + Japanese script + Chinese localization handoff.

Uses original game voice IDs, never semantic similarity or invented transcripts.
No ASR, model training, synthesis, denoising or automatic speech trimming.
Run with the project's .venv Python (numpy + imageio_ffmpeg).
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import csv
import hashlib
from functools import lru_cache
import importlib.util
import json
import mmap
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from zipfile import ZipFile, ZIP_DEFLATED
import zlib

import imageio_ffmpeg
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ROLES = {'hika': ('绯华', '緋華', 'vo2_', 'Hika'), 'ayame': ('菖蒲', '菖蒲', 'vo8_', 'Ayame'),
         'mugi': ('麦', 'むぎ', 'vo1_', 'Mugi')}
REQUIRED = ('utterance_id', 'character_id', 'audio_path', 'ja_text', 'zh_text', 'source_game_file',
            'source_scene_id', 'source_line_id', 'audio_start', 'audio_end', 'audio_language',
            'translation_source', 'alignment_status', 'speaker_confidence', 'transcript_confidence',
            'quality_status', 'review_status')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def json_read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rows_read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def rows_write(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def clean_ja(text):
    return ' '.join((text or '').replace('|', ' ').split()).strip()


@lru_cache(maxsize=128)
def source_lines(filename):
    raw = (ROOT / 'extracted/scenario_all/scenario/main' / filename).read_bytes()
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16').splitlines()
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            return raw.decode(encoding).splitlines()
        except UnicodeError:
            pass
    raise ValueError('Unsupported source encoding')


def spoken_markup_requires_review(occurrences):
    for row in occurrences:
        if 'inline_markup' not in row['parser_uncertainties']:
            continue
        loc = row['source_location']
        body = '\n'.join(source_lines(row['source_file'])[loc['line_start'] - 1:loc['line_end']])
        tags = re.findall(r'\[([^\]]+)\]', body)
        if any(tag not in ('>>', '<<', 'c', 'r', 'icHeart') for tag in tags):
            return True
    return False


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fast_xp3_index(path):
    """Read this game's contiguous tail index in linear time, validating chunk sizes."""
    with Path(path).open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        if mm[:11] != b'XP3\r\n \n\x1a\x8bg\x01':
            raise ValueError('Not a supported XP3 archive')
        boundary = len(mm)
        while True:
            pos = mm.rfind(b'File', 0, boundary)
            if pos < 0 or pos + 12 > boundary:
                break
            size = struct.unpack_from('<Q', mm, pos + 4)[0]
            if pos + 12 + size != boundary:
                break
            boundary = pos
        if boundary == len(mm):
            raise ValueError('No contiguous tail XP3 index')
        cursor, entries = boundary, []
        while cursor < len(mm):
            if mm[cursor:cursor + 4] != b'File':
                raise ValueError('Malformed XP3 index chain')
            size = struct.unpack_from('<Q', mm, cursor + 4)[0]
            end, position = cursor + 12 + size, cursor + 12
            name, adlr, segments = None, 0, []
            while position + 12 <= end:
                kind = mm[position:position + 4]
                length = struct.unpack_from('<Q', mm, position + 4)[0]
                data = mm[position + 12:position + 12 + length]
                if position + 12 + length > end:
                    raise ValueError('Malformed XP3 subchunk')
                if kind == b'info':
                    n = struct.unpack_from('<H', data, 20)[0]
                    name = data[22:22 + n * 2].decode('utf-16-le')
                elif kind == b'adlr':
                    adlr = struct.unpack('<I', data)[0]
                elif kind == b'segm':
                    if len(data) % 28:
                        raise ValueError('Malformed XP3 segments')
                    segments = [struct.unpack_from('<IQQQ', data, i) for i in range(0, len(data), 28)]
                position += 12 + length
            if position != end or not name or not segments:
                raise ValueError('Incomplete XP3 entry')
            entries.append({'name': name, 'adlr': adlr, 'segments': segments})
            cursor = end
    if len({r['name'] for r in entries}) != len(entries):
        raise ValueError('Duplicate XP3 entry names')
    return entries


def read_xp3_member(path, entry):
    import xp3
    key = np.asarray(xp3.make_filter(entry['adlr']), dtype=np.uint8)
    result, position = [], 0
    with Path(path).open('rb') as f:
        for flag, offset, size, compressed in entry['segments']:
            f.seek(offset)
            raw = f.read(compressed if flag else size)
            raw = zlib.decompress(raw) if flag else raw
            if len(raw) != size:
                raise ValueError('XP3 segment size mismatch')
            data = np.frombuffer(raw, dtype=np.uint8)
            # Same filter as the existing extractor; vectorize to avoid re-extracting files.
            stream = key[(np.arange(len(data), dtype=np.int64) + position) % len(key)]
            result.append(np.bitwise_xor(data, stream).tobytes())
            position += len(data)
    return b''.join(result)


def source_alignment(output, game):
    parser = load_module('tts_native_script_parser', ROOT / 'backend/web/documents/utils/story_pipeline.py')
    from text_corpus_v3_common import attach_scenes
    ja_root = ROOT / 'extracted/scenario_all/scenario/main'
    sources = output / 'source_cache'
    patch, data = game / 'patch.xp3', game / 'data.xp3'
    patch_index = {r['name']: r for r in fast_xp3_index(patch)}
    data_index = {r['name']: r for r in fast_xp3_index(data)}
    macro_name = 'scenario/macro/Macro_Effect.ks'
    macro_raw = read_xp3_member(data, data_index[macro_name])
    macro_path = sources / 'policy_evidence/Macro_Effect.ks'
    macro_path.parent.mkdir(parents=True, exist_ok=True)
    macro_path.write_bytes(macro_raw)
    macro_text = parser.decode_source(macro_path)[0]
    if not re.search(r'@macro name="icHeart"\s+@graph storage="ic_heart"[^\n]*char=false', macro_text):
        raise ValueError('Visual heart macro definition changed; do not assume its spoken meaning')
    json_write(output / 'analysis/visual_markup_policy.json', {'tag': 'icHeart',
        'policy': 'nonspoken_graphical_icon_only; other reading-changing markup stays quarantined',
        'source_game_member': macro_name, 'source_sha256': sha(macro_path),
        'source_path_in_package': 'source/policy_evidence/Macro_Effect.ks'})
    occurrences, inventory, scene_variants = [], [], []
    for ja_path in sorted(ja_root.glob('*.ks')):
        if ja_path.name not in patch_index or 'scenario/main/' + ja_path.name not in data_index:
            raise ValueError('Missing game source script')
        ja_raw = read_xp3_member(data, data_index['scenario/main/' + ja_path.name])
        zh_raw = read_xp3_member(patch, patch_index[ja_path.name])
        if ja_path.read_bytes() != ja_raw:
            raise ValueError('Existing Japanese script differs from actual game archive')
        ja_copy, zh_copy = sources / 'ja' / ja_path.name, sources / 'zh' / ja_path.name
        for p, raw in ((ja_copy, ja_raw), (zh_copy, zh_raw)):
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists() and p.read_bytes() != raw:
                raise ValueError('Existing V1 source cache changed')
            if not p.exists():
                p.write_bytes(raw)
        ja_rows, _ = parser.parse_script(ja_copy, sources / 'ja')
        zh_rows, _ = parser.parse_script(zh_copy, sources / 'zh')
        attach_scenes(ja_rows, parser.decode_source(ja_copy)[0])
        if len(ja_rows) != len(zh_rows):
            raise ValueError('JA/ZH script record count differs')
        for ja, zh in zip(ja_rows, zh_rows):
            if any(ja[k] != zh[k] for k in ('id', 'source_file', 'source_location', 'character', 'voice_id', 'segment', 'sequence')):
                raise ValueError('JA/ZH location/voice/speaker metadata mismatch')
            if ja['character'] not in ROLES or not ja['voice_id']:
                continue
            if ja['scene_id'] != zh['scene_id']:
                scene_variants.append({'source_line_id': ja['id'], 'character': ja['character'],
                    'ja_source_scene_id': ja['scene_id'], 'zh_source_scene_id': zh['scene_id'],
                    'reason': 'localized_label_name; physical_line_voice_and_character_still_identical'})
            occurrences.append({'source_line_id': ja['id'], 'character': ja['character'], 'voice_id': ja['voice_id'],
                'source_file': ja['source_file'], 'source_location': ja['source_location'],
                'source_scene_id': ja['scene_id'], 'fine_scene_id': ja['v3_scene'],
                'sequence': ja['sequence'], 'segment': ja['segment'], 'branch': ja['branch'],
                'ja_speaker': ja['speaker'], 'zh_speaker': zh['speaker'],
                'ja_text': ja['text'], 'zh_text': zh['text'], 'text_ja': ja['text'], 'text_zh': zh['text'],
                'ja_script_sha256': ja['source_sha256'], 'zh_script_sha256': zh['source_sha256'],
                'route_id': ja['route_id'], 'parser_uncertainties': ja['uncertainties']})
        inventory.append({'source_file': ja_path.name, 'ja_sha256': sha(ja_copy), 'zh_sha256': sha(zh_copy),
            'source_data_member': 'scenario/main/' + ja_path.name, 'source_patch_member': ja_path.name,
            'ja_path': 'source/ja/' + ja_path.name, 'zh_path': 'source/zh/' + ja_path.name})
    rows_write(output / 'analysis/scene_label_variants.jsonl', scene_variants)
    return occurrences, inventory


def read_v3():
    by_line, packages, partition = {}, [], None
    for path in sorted(ROOT.glob('AIlover_*_Text_V3.zip')):
        with ZipFile(path) as z:
            if z.testzip():
                raise ValueError('Text V3 ZIP corruption')
            pre = z.namelist()[0].split('/')[0] + '/'
            slug = json.loads(z.read(pre + 'package.json'))['character']
            if slug not in ROLES:
                continue
            canon = [json.loads(line) for line in z.read(pre + 'provenance/canonical.jsonl').decode('utf-8').splitlines()]
            for row in canon:
                by_line[row['target_id']] = {'character': slug, 'sample_id': row['sample_id'], 'split': row['split'],
                    'source_text': row['sample']['conversations'][-1]['value']}
            mapping = json.loads(z.read(pre + 'source/partition.json'))['assignment']
            if partition is not None and mapping != partition:
                raise ValueError('V3 roles disagree on global source partition')
            partition = mapping
            packages.append({'path': path.name, 'sha256': sha(path), 'bytes': path.stat().st_size,
                             'character_id': slug, 'canonical_target_count': len(canon)})
    if {r['character_id'] for r in packages} != set(ROLES):
        raise ValueError('Missing actual text V3 packages')
    return by_line, packages, partition


def process_audio(entry, slug, occurrences, voice_archive, extracted, legacy_root, cache, ffmpeg):
    from tts_audio_qc import audio_metrics, quality_reasons, quality_flags
    voice = Path(entry['name']).stem
    raw = read_xp3_member(voice_archive, entry)
    original_sha = hashlib.sha256(raw).hexdigest()
    original_path = extracted / Path(entry['name']).name
    newly_extracted = False
    if original_path.exists():
        if sha(original_path) != original_sha:
            raise ValueError('Extracted original differs from game voice archive: ' + voice)
    else:
        # Only missing natives go into the new V1 area. Existing originals stay read-only.
        original_path = cache / 'missing_native' / Path(entry['name']).name
        original_path.parent.mkdir(parents=True, exist_ok=True)
        if not original_path.exists():
            original_path.write_bytes(raw)
        elif sha(original_path) != original_sha:
            raise ValueError('Missing-native cache changed')
        newly_extracted = True
    ja_variants = sorted({clean_ja(r['ja_text']) for r in occurrences if r['ja_text'].strip()})
    ja_text = ja_variants[0] if len(ja_variants) == 1 else None
    reasons = []
    if not occurrences:
        reasons.append('no_explicit_script_transcript')
    if len(ja_variants) != 1:
        reasons.append('missing_or_conflicting_japanese_transcripts')
    if any(r['character'] != slug or r['ja_speaker'] != ROLES[slug][1] or not r['voice_id'].startswith(ROLES[slug][2]) for r in occurrences):
        reasons.append('speaker_or_voice_prefix_conflict')
    if spoken_markup_requires_review(occurrences):
        reasons.append('inline_spoken_reading_needs_review')
    run = subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(original_path),
                          '-vn', '-ac', '1', '-ar', '32000', '-f', 's16le', 'pipe:1'],
                         capture_output=True, timeout=90)
    result = {'voice_id': voice, 'character_id': slug, 'original_audio_sha256': original_sha,
        'original_audio_bytes': len(raw), 'source_audio_path': original_path.relative_to(ROOT).as_posix(),
        'archive_member': entry['name'], 'archive_segments': entry['segments'], 'archive_filter_seed': entry['adlr'],
        'archive_member_equals_extracted_original': True, 'newly_extracted_missing_native': newly_extracted,
        'ja_text': ja_text, 'ja_variants': ja_variants, 'quality_reasons': reasons,
        'reused_existing_wav': False, 'processing_source_path': None}
    if run.returncode or not run.stdout:
        result['quality_reasons'].append('audio_decode_failed')
        result['decode_error'] = run.stderr.decode('utf-8', errors='replace')[-500:]
        result['metrics'] = None
        result['quality_flags'] = []
        return result
    pcm = run.stdout
    metrics = audio_metrics(pcm, 32000)
    reasons += quality_reasons(metrics, ja_text or '')
    flags = quality_flags(metrics)
    if any('cut' in f or 'boundary' in f for f in flags):
        reasons.append('potential_cut_boundary_requires_human_review')
    result['metrics'], result['quality_flags'] = metrics, flags
    result['quality_reasons'] = sorted(set(reasons))
    if not reasons:
        existing = legacy_root / (voice + '.wav')
        if existing.is_file():
            try:
                with wave.open(str(existing), 'rb') as w:
                    same = (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 32000) and w.readframes(w.getnframes()) == pcm
                if same:
                    result['processing_source_path'] = existing.relative_to(ROOT).as_posix()
                    result['reused_existing_wav'] = True
                    result['existing_wav_sha256'] = sha(existing)
            except (OSError, wave.Error):
                result['existing_wav_read_failed'] = True
        if not result['processing_source_path']:
            destination = cache / slug / (slug + '_' + voice + '.wav')
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                with wave.open(str(destination), 'wb') as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(32000); w.writeframes(pcm)
            else:
                with wave.open(str(destination), 'rb') as w:
                    if w.readframes(w.getnframes()) != pcm:
                        raise ValueError('Processing cache PCM differs')
            result['processing_source_path'] = destination.relative_to(ROOT).as_posix()
        result['processed_audio_sha256'] = sha(ROOT / result['processing_source_path'])
    return result


def analyze(entries, occurrences, output, archive, ffmpeg, workers):
    grouped = defaultdict(list)
    for row in occurrences:
        grouped[row['voice_id']].append(row)
    from tts_audio_qc import __file__ as qc_file
    fingerprint = {'audio_qc_sha256': sha(qc_file), 'ffmpeg_sha256': sha(ffmpeg),
                   'source_alignment_sha256': hashlib.sha256(json.dumps(occurrences, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    fingerprint_path = output / 'analysis/policy_fingerprint.json'
    if fingerprint_path.exists() and json_read(fingerprint_path) != fingerprint:
        raise ValueError('Cached analysis policy/source changed; choose another output directory')
    json_write(fingerprint_path, fingerprint)
    journal = output / 'analysis/audio_qc.jsonl'
    cached = {r['voice_id']: r for r in rows_read(journal)} if journal.is_file() else {}
    selected = [(r, slug) for r in entries for slug, role in ROLES.items() if Path(r['name']).name.startswith(role[2])]
    jobs, result = [], []
    for entry, slug in selected:
        old = cached.get(Path(entry['name']).stem)
        if (old and 'inline_spoken_reading_needs_review' in old['quality_reasons']
                and not spoken_markup_requires_review(grouped[Path(entry['name']).stem])):
            # Earlier cache quarantined a visual heart icon. Only these newly
            # admitted clips need decoding to recover their unretained PCM.
            old = None
        if old:
            if sha(ROOT / old['source_audio_path']) != old['original_audio_sha256']:
                raise ValueError('Cached original source changed')
            if old['processing_source_path'] and sha(ROOT / old['processing_source_path']) != old['processed_audio_sha256']:
                raise ValueError('Cached processed source changed')
            result.append(old)
        else:
            jobs.append((entry, slug))
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open('a', encoding='utf-8') as log, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for entry, slug in jobs:
            legacy = ROOT / ('finetune_data/mugi/tts/dataset/mugi' if slug == 'mugi' else f'finetune_data/tts/dataset/{slug}')
            future = pool.submit(process_audio, entry, slug, grouped[Path(entry['name']).stem], archive,
                                 ROOT / 'extracted/voice', legacy, output / 'processing_cache', ffmpeg)
            futures[future] = entry['name']
        for done, future in enumerate(as_completed(futures), 1):
            row = future.result()
            log.write(json.dumps(row, ensure_ascii=False) + '\n'); log.flush()
            result.append(row)
            if done % 250 == 0 or done == len(jobs):
                print(f'Native decode/QC {done}/{len(jobs)}; cached={len(cached)}', flush=True)
    return sorted(result, key=lambda r: (r['character_id'], r['voice_id']))


def form_index(analysis, occurrences, partition):
    by_voice = defaultdict(list)
    for row in occurrences:
        by_voice[row['voice_id']].append(row)
    records = []
    for audio in analysis:
        slug, voice = audio['character_id'], audio['voice_id']
        source = by_voice[voice]
        texts = sorted({r['zh_text'] for r in source if r['zh_text'].strip()})
        reasons = audio['quality_reasons'][:]
        files = sorted({r['source_file'] for r in source})
        if len(files) > 1:
            reasons.append('cross_file_reuse_needs_group_resolution')
        group = files[0] if files else 'unknown:' + voice
        split = partition.get(group)
        if not split:
            bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 100
            split = 'validation' if bucket < 12 else 'test' if bucket < 24 else 'train'
        accepted = not reasons
        duration = audio['metrics']['duration_seconds'] if audio['metrics'] else None
        record = {key: None for key in REQUIRED}
        record.update({'utterance_id': f'{slug}_{voice}_{audio["original_audio_sha256"][:12]}',
            'character_id': slug, 'voice_id': voice, 'audio_language': 'ja', 'ja_text': audio['ja_text'],
            'zh_text': texts[0] if len(texts) == 1 else None,
            'zh_variants': [{'zh_text': text, 'source_line_ids': [r['source_line_id'] for r in source if r['zh_text'] == text]} for text in texts],
            'audio_path': f'tts_adaptation/{slug}/audio/{slug}_{voice}.wav' if accepted else audio['source_audio_path'],
            'audio_path_scope': 'package' if accepted else 'external',
            'source_game_file': files[0] if len(files) == 1 else None,
            'source_scene_id': source[0]['source_scene_id'] if len(source) == 1 else None,
            'source_line_id': source[0]['source_line_id'] if source else None,
            'source_occurrences': source, 'source_line_ids': [r['source_line_id'] for r in source],
            'audio_start': 0.0 if duration else None, 'audio_end': duration,
            'timestamp_basis': 'whole_native_voice_file_no_game_scene_timeline',
            'duration_seconds': duration, 'translation_source': 'user_local_game_patch.xp3',
            'alignment_status': ('missing_script' if not source else 'conflicting_ja_transcripts' if len(audio['ja_variants']) != 1
                else 'aligned_multiple_zh_variants' if len(texts) > 1 else 'aligned_explicit_voice_and_line_id'),
            'speaker_confidence': 'explicit_script_speaker_plus_voice_prefix_and_archive' if source and not any('speaker' in r for r in reasons) else 'prefix_or_folder_only_not_confirmed',
            'transcript_confidence': 'script_voice_id_exact_not_listening_verified' if audio['ja_text'] else 'unavailable_or_conflicting',
            'quality_status': 'technical_pass_content_pending_listening' if accepted else 'excluded_needs_review',
            'quality_reasons': sorted(set(reasons)), 'quality_flags': audio['quality_flags'],
            'review_status': 'requires_human_listening_and_translation_review',
            'music_overlap_review': 'not_measured_no_source_separation_or_diarization_run',
            'metrics': audio['metrics'], 'split': split if accepted else 'excluded',
            'partition_group': group, 'partition_group_split': split,
            'original_audio_sha256': audio['original_audio_sha256'], 'original_audio_bytes': audio['original_audio_bytes'],
            'source_audio_path': audio['source_audio_path'], 'source_audio_archive': '国王恋爱/voice.xp3',
            'source_archive_member': audio['archive_member'], 'archive_segments': audio['archive_segments'],
            'archive_member_equals_extracted_original': True,
            'processed_audio_sha256': audio.get('processed_audio_sha256'),
            'pcm_sha256': audio['metrics']['pcm_sha256'] if audio['metrics'] else None,
            'reused_existing_wav': audio['reused_existing_wav']})
        records.append(record)
    # Detect duplicate PCM across voices before assigning training labels.
    by_pcm = defaultdict(list)
    for r in records:
        if r['quality_status'].startswith('technical_pass'):
            by_pcm[r['pcm_sha256']].append(r)
    for same in by_pcm.values():
        if len(same) < 2:
            continue
        conflict = len({(r['character_id'], r['ja_text']) for r in same}) != 1
        for row in same if conflict else same[1:]:
            row['quality_status'] = 'excluded_needs_review'
            row['quality_reasons'].append('duplicate_audio_conflicting_transcript_or_speaker' if conflict else 'duplicate_pcm_audio')
            row['duplicate_of'] = same[0]['utterance_id']
            row['audio_path'] = row['source_audio_path']; row['audio_path_scope'] = 'external'; row['split'] = 'excluded'
    return records


def choose_references_and_fewshot(records, v3_lines):
    references, fewshot = {}, {}
    for slug in ROLES:
        candidates = [r for r in records if r['character_id'] == slug and r['split'] == 'train'
                      and 5 <= r['duration_seconds'] <= 10 and r['metrics']['rms'] >= 800
                      and not r['quality_flags'] and any(i in v3_lines for i in r['source_line_ids'])]
        candidates.sort(key=lambda r: (abs(r['metrics']['rms'] - 2500), r['utterance_id']))
        chosen, files = [], set()
        for row in candidates:
            if row['partition_group'] not in files:
                chosen.append(row); files.add(row['partition_group'])
            if len(chosen) == 3:
                break
        if len(chosen) < 3:
            raise ValueError('Not enough diverse technically clean daily reference candidates: ' + slug)
        for row in chosen:
            row['split'] = 'reference'
        references[slug] = [{'utterance_id': r['utterance_id'], 'audio_path': r['audio_path'], 'ja_text': r['ja_text'],
            'duration_seconds': r['duration_seconds'], 'source_line_ids': r['source_line_ids'],
            'selection_reason': '5-10s; clear RMS/peak/boundary metrics; V3 daily line; diverse train-source files; no automatic claim of optimal voice',
            'review_status': 'provisional_requires_human_listening', 'metrics': r['metrics']} for r in chosen]
        pool = [r for r in records if r['character_id'] == slug and r['split'] == 'train'
                and 3 <= r['duration_seconds'] <= 10 and r['metrics']['rms'] >= 800 and not r['quality_flags']
                and any(i in v3_lines for i in r['source_line_ids'])]
        groups = defaultdict(list)
        for row in sorted(pool, key=lambda r: r['utterance_id']):
            groups[row['partition_group']].append(row)
        selected, seconds = [], 0
        while any(groups.values()):
            for group in sorted(groups):
                if groups[group]:
                    row = groups[group].pop(0)
                    if seconds + row['duration_seconds'] <= 900:
                        selected.append(row); seconds += row['duration_seconds']
        fewshot[slug] = selected
    return references, fewshot


def bonus_records(inventory):
    result = []
    for slug, data in inventory.get('bonus_audio', {}).items():
        if slug not in ROLES:
            continue
        for item in data['files']:
            source = Path(item['path'])
            if sha(source) != item['sha256']:
                raise ValueError('Bonus original changed since inventory')
            row = {key: None for key in REQUIRED}
            duration = item['duration_seconds']
            relative = source.relative_to(ROOT).as_posix()
            row.update({'utterance_id': f'{slug}_bonus_{source.stem}_{item["sha256"][:12]}',
                'character_id': slug, 'voice_id': 'bonus_' + slug + '_' + source.stem,
                'audio_path': relative, 'audio_path_scope': 'external', 'audio_language': 'ja',
                'source_audio_path': relative, 'source_occurrences': [], 'source_line_ids': [], 'zh_variants': [],
                'audio_start': 0.0, 'audio_end': duration, 'duration_seconds': duration,
                'timestamp_basis': 'whole_original_bonus_WAV_no_scene_timeline',
                'translation_source': 'no_matching_script_or_localization', 'alignment_status': 'missing_script',
                'speaker_confidence': 'bonus_folder_only_not_script_confirmed',
                'transcript_confidence': 'unavailable_ASR_not_run', 'quality_status': 'excluded_needs_review',
                'quality_reasons': ['bonus_original_without_reliable_script_transcript'],
                'quality_flags': [], 'review_status': 'requires_japanese_transcription_and_listening',
                'music_overlap_review': 'not_measured', 'original_audio_sha256': item['sha256'],
                'original_audio_bytes': item['bytes'], 'original_format': {k: item[k] for k in ('sample_rate', 'channels', 'sample_width_bytes')},
                'metrics': None, 'pcm_sha256': None, 'processed_audio_sha256': None,
                'split': 'excluded', 'partition_group': None, 'partition_group_split': None,
                'reused_existing_wav': False, 'original_kind': 'bonus_untranscribed'})
            result.append(row)
    return result


def chinese_targets(records, v3_lines):
    targets, excluded = [], []
    for row in records:
        for occurrence in row['source_occurrences']:
            text = occurrence['zh_text']
            issue = None
            if not 2 <= len(text.strip()) <= 600 or not re.search(r'[\u4e00-\u9fff]', text):
                issue = 'too_short_nonlinguistic_or_long'
            elif re.search(r'[\u3040-\u30ff\uff66-\uff9f]|\ufffd|\[[^\]]+\]', text):
                issue = 'language_or_markup_requires_review'
            linked = v3_lines.get(occurrence['source_line_id'])
            target = {'utterance_id': row['utterance_id'], 'character_id': row['character_id'],
                'source_line_id': occurrence['source_line_id'], 'zh_text': text,
                'source_game_file': occurrence['source_file'], 'source_scene_id': occurrence['source_scene_id'],
                'source_location': occurrence['source_location'], 'translation_source': 'original_user_patch.xp3',
                'text_quality_status': ('v3_structural_pass_not_human_certified' if linked else 'localized_script_format_pass_pending_review') if not issue else issue,
                'v3_sample_id': linked['sample_id'] if linked else None, 'v3_split': linked['split'] if linked else None,
                'audio_language_is_ja_not_zh_supervision': True}
            (excluded if issue and not linked else targets).append(target)
    return targets, excluded


def role_statistics(slug, records, analysis, raw_inventory, references, fewshot, targets):
    role = [r for r in records if r['character_id'] == slug]
    native = [r for r in role if r.get('original_kind') != 'bonus_untranscribed']
    accepted = [r for r in role if r['audio_path_scope'] == 'package']
    bonus = [r for r in role if r.get('original_kind') == 'bonus_untranscribed']
    accurate_links = [r for r in native if r['ja_text'] and r['source_occurrences']]
    bilingual = [r for r in accurate_links if r['zh_text'] is not None or r['zh_variants']]
    own_analysis = [r for r in analysis if r['character_id'] == slug]
    reasons = Counter(reason for r in role for reason in r['quality_reasons'])
    seconds = sum(r['duration_seconds'] for r in accepted)
    return {'character_id': slug, 'name': ROLES[slug][0], 'native_opus_count': len(native),
        'native_opus_duration_hours': raw_inventory['roles'][slug]['opus']['duration_hours'],
        'original_including_bonus_count': len(role), 'bonus_count': len(bonus),
        'bonus_duration_seconds': round(sum(r['duration_seconds'] for r in bonus), 6),
        'already_extracted_opus_count': raw_inventory['roles'][slug]['opus']['files'],
        'old_converted_wav_count': raw_inventory['roles'][slug]['existing_wav']['files'],
        'old_converted_wav_duration_hours': raw_inventory['roles'][slug]['existing_wav']['duration_hours'],
        'source_speaker_confirmed_native_count': sum(r['speaker_confidence'].startswith('explicit_script') for r in native),
        'script_linked_japanese_transcript_count': len(accurate_links),
        'listening_certified_japanese_transcript_count': 0,
        'reliable_game_id_bilingual_alignment_count': len(bilingual),
        'multiple_zh_translation_variants_count': sum(len(r['zh_variants']) > 1 for r in native),
        'accepted_japanese_audio_count': len(accepted), 'accepted_duration_seconds': round(seconds, 6),
        'accepted_duration_hours': round(seconds / 3600, 6), 'excluded_count': len(role) - len(accepted),
        'exclusion_reasons': dict(reasons), 'quality_flags': dict(Counter(f for r in role for f in r['quality_flags'])),
        'actual_new_native_extractions': sum(r['newly_extracted_missing_native'] for r in own_analysis),
        'verified_existing_wav_reused': sum(r['reused_existing_wav'] for r in own_analysis),
        'new_or_corrected_wav_copies': sum(bool(r['processing_source_path']) and not r['reused_existing_wav'] for r in own_analysis),
        'splits': {split: {'files': sum(r['split'] == split for r in accepted),
                           'seconds': round(sum(r['duration_seconds'] for r in accepted if r['split'] == split), 6)}
                   for split in ('train', 'validation', 'test', 'reference')},
        'fewshot_files': len(fewshot[slug]), 'fewshot_minutes': round(sum(r['duration_seconds'] for r in fewshot[slug]) / 60, 4),
        'reference_files': len(references[slug]), 'reference_listen_certified': False,
        'chinese_target_texts': sum(r['character_id'] == slug for r in targets),
        'v3_target_mappings': sum(r['character_id'] == slug and bool(r['v3_sample_id']) for r in targets),
        'raw_native_audio_full_decode_checked': len(own_analysis),
        'confirmed_overlapping_speakers_count': None, 'confirmed_strong_bgm_count': None,
        'confirmed_cutoff_count': None, 'unmeasured_requires_listening': ['overlap', 'BGM', 'audible_cutoff', 'spoken_script_accuracy'],
        'accepted_definition': 'Explicit speaker/JA script link + native archive equality + technical waveform pass, not a human listening certificate'}


def review_csv(path, records, references):
    sampled = []
    for slug in references:
        role = [r for r in records if r['character_id'] == slug]
        refs = {r['utterance_id'] for r in references[slug]}
        selected = [r for r in role if r['utterance_id'] in refs]
        passes = [r for r in role if r['audio_path_scope'] == 'package' and r['utterance_id'] not in refs]
        for split in ('train', 'validation', 'test'):
            own = [r for r in passes if r['split'] == split]
            selected += own[::max(1, len(own) // 12)][:12]
        grouped = defaultdict(list)
        for r in role:
            if r['quality_reasons']:
                grouped[r['quality_reasons'][0]].append(r)
        pending = []
        while any(grouped.values()) and len(pending) < 21:
            for reason in sorted(grouped):
                if grouped[reason] and len(pending) < 21:
                    pending.append(grouped[reason].pop(0))
        selected += pending
        sampled += [{'character_id': slug, 'utterance_id': r['utterance_id'], 'audio_path': r['audio_path'],
            'audio_scope': r['audio_path_scope'], 'ja_text': r['ja_text'] or '',
            'zh_text_or_variants': r['zh_text'] or json.dumps(r['zh_variants'], ensure_ascii=False),
            'duration_seconds': r['duration_seconds'], 'status': r['quality_status'],
            'automatic_findings': '|'.join(r['quality_reasons'] + r['quality_flags']),
            'human_ja_match': '', 'single_speaker': '', 'bgm_ok': '', 'word_boundaries_ok': '',
            'translation_ok': '', 'reviewer': '', 'notes': ''} for r in selected]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(sampled[0]))
        writer.writeheader()
        for row in sampled:
            writer.writerow({k: "'" + str(v) if str(v).startswith(('=', '+', '-', '@')) else v for k, v in row.items()})
    return dict(Counter(r['character_id'] for r in sampled))


def readme_text(roles, stats):
    summary = '\n'.join(f"- {ROLES[s][0]}：合格日语音频 {stats[s]['accepted_japanese_audio_count']} 段，{stats[s]['accepted_duration_hours']:.3f} 小时；少样本 {stats[s]['fewshot_minutes']:.2f} 分钟。" for s in roles)
    return f'''# AIlover 三角色中文语音微调准备包 V1

日期：2026-10-23。本包是**日语原声适配数据 + 对应中文文本**，不是中文录音监督集。
只准备材料；没有训练模型、运行推理基线、ASR、合成语音或重构应用。

{summary}

## 数据层与使用顺序

1. `tts_adaptation/角色/audio/`：1–20秒原生完整台词的处理副本，32 kHz、mono、16-bit PCM。
   保留游戏原句边界，没有再切片、自动删静音、降噪或拼接台词；不覆盖原始Opus/旧WAV。
2. `labels/all.list` 是完整合格档案；`train/validation/test.list` 按原.ks文件分组。
   三位分区继承文本V3已有全局文件划分，新增文件使用稳定哈希分配；不为凑比例拆散场景。
   不要把all.list作为无条件默认训练输入，里面含验证、测试和保留参考；正式准备使用train.list。
3. `fewshot_15min.list`：train内按多个源文件交替选取的少样本子集，最多十五分钟，不复制额外音频。
   **完整合格语料并未缩减成十五分钟**，全量与快速子集分别保留。
4. `references/角色.json`：每位三组参考及日文文本，引用同一音频，不重复储存。
   候选来自V3日常台词、训练来源文件、5–10秒和数值质检；已重新选择，不认定旧参考或本次候选最优。
   参考ID不进入train/val/test或fewshot标签，仍在all档案中，后续必须先试听。

## GPT-SoVITS 兼容清单

格式严格为 `audio_path|speaker_name|ja|actual_japanese_transcript`。路径相对整包根目录，speaker为hika/ayame/mugi。
日语音频的语种始终ja，第四列始终源剧本日语，不把中文汉化当成其朗读标签。
每位分别创建实验；说话人列不是自动多角色隔离开关，不要拼三人清单当作已验证的多说话人模型。

先解压，使用 Python 3.10+（校验器只依赖标准库）：
`python -B tools/verify.py verify --root /整包根目录`
在最终训练机器上生成绝对路径清单：
`python -B tools/verify.py paths --root /整包根目录 --character {roles[0]}`
此命令只在包外兄弟目录写新.list，不修改已清单受控的交付文件。
验证/测试保留用于后续评测，不能因为路径可读就自动全部合并训练；本次没有启动训练。

## 对齐和中文目标

`alignment/index.jsonl`：本包角色所有原始逐句音频和特典候选的总账，包括排除项，不静默丢弃。
utterance_id绑定角色、原游戏voice_id和原音频SHA，source_line_id绑定具体剧本出现位置及双方文件SHA。
同一voice可能多次出现，完整source_occurrences保留，不以语义相近猜对应。
`crosslingual_alignment/`：显式voice+物理行对齐的日语声音/日语台词/中文汉化映射；包括不适合训练但可追溯的对应。
多中文译文保留zh_variants及各source_line_ids，不任意折叠。route_id缺失时保持未知，不把文件名前缀猜成路线。
原作与汉化的标签名可能不同，source/scene_label_variants.jsonl保留双名；source_scene_id以原日文标签为准，按物理行和voice核对。
`zh_target_text/`：仅引用和映射原汉化/V3，不修改V3，标记自动格式合格或待人工校译。
它们用于未来中文合成的目标文字，不能填入日语WAV的监督转写字段。
`source/ja`、`source/zh`、来源清单仅为校对，不能整目录当成额外训练资料。
`audio_start/end`只表示完整原生语音文件的本地范围；没有伪造游戏场景时间线。

`zh_supervised_data_status.json`：真实中文录音=0，真实中文声音+准确中文转写配对=0。
当前支持日语角色适配材料和未来多语种模型的日语参考→中文文本跨语言任务。
要做真正中文语音监督训练，仍需真实中文配音及逐句准确中文转写、来源和使用授权；生成音频不能冒充原配录音。

## 质检的实际边界

所有原生Opus均与voice.xp3对应解密项做字节哈希核对，并实际FFmpeg解码；存在的32k WAV仅在PCM与本次原声解码完全一致时复用。
数值阈值1–20秒、RMS/帧能量、饱和比例和端点风险是本项目策略，不是官方通用片段长度规定。
潜在切边、坏文件、无准确脚本、非语言发声、严重饱和等记录排除；高峰值本身只作标记，不能当成已经削波。
日语转写是显式游戏脚本关联，不是ASR或人工听审证书。没有进行源分离、声纹或多人检测，
因此**BGM、多人重叠、真实读音/字幕差异和实际截断的确认数量是未测，不是零**。
合格定义为来源与技术层面通过，待人工试听；audit/listening_review.csv 留空等待实际审查，qa报告不冒充试听结果。
特典、无脚本和问题音频保留外部原路径与SHA；为了不重复分发，它们不装入训练音频目录。
外部路径在另一机器不保证存在，校验器只要求本包已收录的合格音频可读。

官方资料提示全量单语微调可能影响跨语言能力，少样本与全量应独立试验，不能保证哪种中文效果最好。
应先固定GPT-SoVITS仓库commit、底模和版本；当前上游v5少样本微调尚未验证，不可沿用其它版本参数。
详见RESEARCH.md的官方源码/维护者文档。本次只交材料，不启动任何训练或推理。
'''


def write_package_metadata(folder, roles, records, occurrences, scripts, source_inventory,
                           v3_packages, references, fewshot, targets, target_excluded, stats, output):
    folder.mkdir(parents=True, exist_ok=False)
    own = [r for r in records if r['character_id'] in roles]
    own_occurrences = [r for r in occurrences if r['character'] in roles]
    own_targets = [r for r in targets if r['character_id'] in roles]
    rows_write(folder / 'source/scene_label_variants.jsonl', [r for r in rows_read(output / 'analysis/scene_label_variants.jsonl') if r['character'] in roles])
    json_write(folder / 'package.json', {'version': 1, 'kind': 'TTS_finetune_preparation', 'characters': roles,
        'source_audio_language': 'ja', 'future_target_language': 'zh', 'date': '2026-10-23',
        'models_trained': False, 'inference_baselines_run': False, 'ASR_run': False, 'app_modified': False})
    rows_write(folder / 'alignment/index.jsonl', own)
    rows_write(folder / 'source/occurrences.jsonl', own_occurrences)
    files = {r['source_file'] for r in own_occurrences}
    selected_scripts = [r for r in scripts if r['source_file'] in files]
    json_write(folder / 'source/inventory.json', {'scripts': selected_scripts, 'archives': source_inventory,
        'native_voice_member_hashes_in_alignment_index': True, 'source_line_id_algorithm': 'SHA256(relative_file:line_start:line_end:ordinal)[:24]'})
    evidence = folder / 'source/policy_evidence/Macro_Effect.ks'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(output / 'source_cache/policy_evidence/Macro_Effect.ks', evidence)
    json_write(folder / 'source/visual_markup_policy.json', json_read(output / 'analysis/visual_markup_policy.json'))
    for source in selected_scripts:
        for language, key in (('ja', 'ja_path'), ('zh', 'zh_path')):
            dest = folder / source[key]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output / 'source_cache' / language / source['source_file'], dest)
    for slug in roles:
        accepted = [r for r in own if r['character_id'] == slug and r['audio_path_scope'] == 'package']
        excluded = [r for r in own if r['character_id'] == slug and r['audio_path_scope'] != 'package']
        rows_write(folder / f'tts_adaptation/{slug}/accepted.jsonl', accepted)
        rows_write(folder / f'tts_adaptation/{slug}/excluded.jsonl', excluded)
        write_lists(folder, slug, accepted, fewshot[slug])
        json_write(folder / f'references/{slug}.json', references[slug])
        aligned = [r for r in own if r['character_id'] == slug and r['source_occurrences'] and r['ja_text']
                   and (r['zh_text'] is not None or r['zh_variants'])]
        rows_write(folder / f'crosslingual_alignment/{slug}.jsonl', aligned)
        rows_write(folder / f'zh_target_text/{slug}.jsonl', [r for r in own_targets if r['character_id'] == slug])
        rows_write(folder / f'zh_target_text/{slug}_excluded.jsonl', [r for r in target_excluded if r['character_id'] == slug])
        json_write(folder / f'tts_adaptation/{slug}/qa.json', stats[slug])
    json_write(folder / 'source/text_v3_references.json', v3_packages)
    json_write(folder / 'zh_supervised_data_status.json', {
        'actual_chinese_recordings': 0, 'valid_zh_audio_text_pairs': 0,
        'japanese_wavs_are_not_chinese_supervision': True,
        'supported': ['Japanese audio + Japanese transcription character adaptation', 'future multilingual Japanese reference to Chinese target cross-language synthesis'],
        'not_currently_supported': ['supervised Mandarin speech training using authentic matching Mandarin recordings'],
        'missing': ['real Mandarin recordings of intended voice', 'accurate Mandarin transcriptions', 'provenance and rights for those recordings'],
        'generated_audio_is_not_authentic_original_dubbing': True})
    json_write(folder / 'qa.json', {s: stats[s] for s in roles})
    review_counts = review_csv(folder / 'audit/listening_review.csv', own, {s: references[s] for s in roles})
    json_write(folder / 'audit/sampling_status.json', {'technical_audio_decode_coverage': 'all native Opus',
        'human_listened_files': 0, 'sampled_pending_human': review_counts, 'review_fields_intentionally_blank': True})
    (folder / 'README.md').write_text(readme_text(roles, stats), encoding='utf-8')
    shutil.copyfile(ROOT / 'docs/TTS_PREPARATION_RESEARCH.md', folder / 'RESEARCH.md')
    (folder / 'tools').mkdir()
    shutil.copyfile(ROOT / 'scripts/tts_preparation_verify.py', folder / 'tools/verify.py')


def build_delivery(output, records, analysis, occurrences, scripts, source_inventory, v3_lines,
                   v3_packages, references, fewshot, publish, package_build, resume_packaging=False):
    delivery = output / 'package_builds' / package_build
    delivery.mkdir(parents=True, exist_ok=resume_packaging)
    raw_inventory = json_read(ROOT / 'finetune_data/tts_preparation_v1_audit/inventory.json')
    bonus = bonus_records(raw_inventory)
    records = records + bonus
    targets, target_excluded = chinese_targets(records, v3_lines)
    if {r['source_line_id'] for r in targets if r['v3_sample_id']} != set(v3_lines):
        raise ValueError('Chinese target mapping does not preserve every text V3 target')
    stats = {slug: role_statistics(slug, records, analysis, raw_inventory, references, fewshot, targets) for slug in ROLES}
    json_write(output / 'analysis/final_statistics.json', stats)
    rows_write(output / 'analysis/final_utterance_index.jsonl', records)
    source_by_voice = {r['voice_id']: r for r in analysis}
    audio_map = {r['audio_path']: ROOT / source_by_voice[r['voice_id']]['processing_source_path']
                 for r in records if r['audio_path_scope'] == 'package'}
    archives = []
    master_name = 'AIlover_TTS_Finetune_Preparation_V1'
    packages = [(master_name, list(ROLES))] + [(f'AIlover_{r[3]}_TTS_Preparation_V1', [slug]) for slug, r in ROLES.items()]
    for name, roles in packages:
        folder = delivery / 'metadata' / name
        archive = delivery / (name + '.zip')
        if folder.exists() and not (resume_packaging and archive.is_file()):
            # Failed packaging can be resumed without decoding or mutating previous inputs.
            raise ValueError('Metadata already exists; choose --package-retry after inspecting the failed output: ' + str(folder))
        if resume_packaging and archive.is_file():
            print('Rechecking existing archive before resuming: ' + archive.name, flush=True)
            digest = sha(archive)
        else:
            write_package_metadata(folder, roles, records, occurrences, scripts, source_inventory,
                                   v3_packages, references, fewshot, targets, target_excluded, stats, output)
            print('Writing ' + archive.name, flush=True)
            digest = zip_package(folder, audio_map, archive, roles)
        if len(roles) == 3:
            checks = extracted_verify(archive, delivery / 'verified_delivery')
        else:
            # Fresh temporary extraction, verified to stay in this V1 workspace before cleanup.
            with tempfile.TemporaryDirectory(prefix='verify-role-', dir=delivery) as tmp:
                temp = Path(tmp).resolve()
                if not temp.is_relative_to(delivery.resolve()):
                    raise ValueError('Unsafe verification temporary path')
                checks = extracted_verify(archive, temp)
        archives.append({'file': archive.name, 'characters': roles, 'bytes': archive.stat().st_size,
                         'sha256': digest, 'checks': checks})
        print('ZIP re-extracted and fully checked: ' + archive.name, flush=True)
    for r in analysis:
        if sha(ROOT / r['source_audio_path']) != r['original_audio_sha256']:
            raise ValueError('Original Opus changed after preparing data')
        if r['reused_existing_wav'] and sha(ROOT / r['processing_source_path']) != r['existing_wav_sha256']:
            raise ValueError('Reused old WAV changed')
    for r in bonus:
        if sha(ROOT / r['source_audio_path']) != r['original_audio_sha256']:
            raise ValueError('Original bonus WAV changed')
    for name, value in source_inventory.items():
        if sha(ROOT / '国王恋爱' / name) != value:
            raise ValueError('Game source archive changed')
    for r in v3_packages:
        if sha(ROOT / r['path']) != r['sha256']:
            raise ValueError('Text V3 changed')
    previous = json_read(ROOT / 'extracted/characters/mugi/existing_data_before.json')
    if any(sha(ROOT / r['path']) != r['sha256'] for r in previous):
        raise ValueError('An existing frozen character file changed')
    checks = {'date': '2026-10-23', 'archives': archives, 'characters': stats,
        'native_opus_decoded': len(analysis), 'bonus_untranscribed': len(bonus),
        'original_source_archives_unchanged': True, 'all_original_Opus_unchanged': True,
        'text_v3_unchanged': True, 'legacy_frozen_file_hashes_rechecked': len(previous),
        'actual_chinese_recordings': 0, 'valid_zh_audio_text_pairs': 0,
        'no_training_inference_or_ASR': True, 'new_native_extractions': sum(r['newly_extracted_missing_native'] for r in analysis)}
    json_write(delivery / 'AIlover_TTS_V1_校验.json', checks)
    report = report_text(stats, archives, checks)
    (delivery / 'AIlover_TTS_V1_报告.md').write_text(report, encoding='utf-8')
    if publish:
        names = [r['file'] for r in archives] + ['AIlover_TTS_V1_校验.json', 'AIlover_TTS_V1_报告.md']
        if any((ROOT / name).exists() for name in names):
            raise ValueError('Refusing to overwrite an existing root V1 deliverable')
        for name in names:
            shutil.copyfile(delivery / name, ROOT / name)
    print('Preparation complete: ' + str(delivery), flush=True)


def report_text(stats, archives, checks):
    report = '# 三角色日语原声适配与中文目标文本：V1 交付报告\n\n日期：2026-10-23。只整理数据，未训练、未运行推理或ASR、未修改应用或文本V3。\n\n'
    report += '|角色|原始/已提取Opus|原始小时|剧本日文标签|中日可靠对应|技术合格段/小时|少样本分钟|\n|---|---:|---:|---:|---:|---|---:|\n'
    for slug, r in stats.items():
        report += f"|{r['name']}|{r['native_opus_count']} / {r['already_extracted_opus_count']}|{r['native_opus_duration_hours']:.3f}|{r['script_linked_japanese_transcript_count']}|{r['reliable_game_id_bilingual_alignment_count']}|{r['accepted_japanese_audio_count']} / {r['accepted_duration_hours']:.3f}|{r['fewshot_minutes']:.2f}|\n"
    report += '\n“日文标签/可靠对应”是明确游戏voice_id、角色、物理行、双方剧本SHA支持的结构对应，非逐条人工听审证书。人工确认准确朗读的数量目前为0，不能把自动关联宣称成已全部听审。\n'
    report += '\n## 分角色质检与完整性\n\n'
    for slug, r in stats.items():
        report += f"### {r['name']}\n\n原始角色确认 {r['source_speaker_confirmed_native_count']}；另有未转写特典 {r['bonus_count']} 段/{r['bonus_duration_seconds']:.3f} 秒，单独隔离。旧WAV {r['old_converted_wav_count']} 段/{r['old_converted_wav_duration_hours']:.3f} 小时。\n"
        report += f"复用逐PCM相等的旧WAV {r['verified_existing_wav_reused']} 段；新建或纠正处理副本 {r['new_or_corrected_wav_copies']}，新增原始提取 {r['actual_new_native_extractions']}。完整合格语料保留，并非只交十五分钟。\n"
        report += f"划分：`{json.dumps(r['splits'],ensure_ascii=False)}`；参考 {r['reference_files']} 段（待试听）；中文目标 {r['chinese_target_texts']}，其中V3目标映射 {r['v3_target_mappings']}。\n"
        report += f"排除 {r['excluded_count']}，逐文件原因在excluded.jsonl，计数：`{json.dumps(r['exclusion_reasons'],ensure_ascii=False)}`。同一文件可有多个原因。\n"
        report += f"软标记：`{json.dumps(r['quality_flags'],ensure_ascii=False)}`。高峰值不是确认削波；潜在边界风险需要听审，不能直接称为已经截断。\n\n"
    report += '''## 索引、标签与语种

原档voice.xp3共12885项，本次只处理三个角色的5978个逐句Opus，全部先用原始档解密字节核对，再实际解码。
另52个真实特典WAV无可靠剧本转写，保留文件路径、哈希、时长和排除状态，没有猜台词或自动进入训练。
全部音频总账包含6030项（原生加特典）；合格、排除、可靠对齐、中文目标清单互相可追溯。
同voice_id可多次出现，日文一致才合并为一条音频标签；绯华vo2_0326的两份中文译文及各来源行均保留。
原始JA与汉化ZH逐行核对ID、文件、物理行、角色、voice ID、顺序及源哈希；不按语义相似度猜映射。
脚本route_id未知时保持null，未擅自将章节文件名解读成路线语义。audio_start/end仅为原始逐句文件范围，不是游戏时间轴。
汉化中存在场景标签名翻译，另存scene_label_variants.jsonl逐行保留JA/ZH双名，不将名称不同误判成另一段音频。

标签严格 `audio_path|speaker|ja|日文实际剧本`，没有中文替换日文转写。中文译稿独立存放，供后续跨语言目标使用。
中文监督集真实状态为0条真实中文录音、0个真实中文音频与准确中文转写配对。日语参考→中文合成依靠未来所选多语种底模的能力，
本次数据不等同于已训练好中文声音，也不保证适配后的口音、音色或自然度。

## 听审边界和不足

所有原生音频均做可解码、时长、32k PCM、RMS、帧能量、饱和比例、端点、源哈希、精确PCM重复等技术检查。
1–20秒是本项目当前筛选策略，非官方统一要求；没有自动剪切词头/词尾或删掉语音边界。
未运行背景音乐分离、多人重叠检测或人工试听，因此严重BGM、重叠、真实截断、实际朗读与字幕差异的确认数量均是“未测”，不是零。
技术合格段仍需人工按audit/listening_review.csv核对，参考音频也未冒充最优候选。52个特典和当前脚本未覆盖的原声最缺准确日文转写。
三位的主体日文来源均足以进入后续适配数据审查；目前共同缺的是逐条听审、中文真实录音，以及固定模型版本后的效果评测。
本次没有某位完全没有可用日文素材的情况，不以数据小时数替代模型效果结论。

当前可支持：独立角色的日语音频+日语文本适配准备；未来多语种模型使用日语参考和中文目标的跨语言任务。
当前不能支持真实中文语音监督训练；需补充目标音色真实中文配音、准确逐句转写、自然边界、来源与使用授权。
合成语音不能冒充真实游戏配音；如未来构造合成教师数据，必须另列来源且不能把它当真实原声验收。

## 分区、参考与模型版本

按整个.ks源文件划分，沿用文本V3的既有文件分区，其余文件稳定分配；所有同源派生语音不跨train/validation/test。
参考从训练来源中单独预留，不进三套训练/验证/测试标签；all.list是全量档案，不是无条件默认训练清单。
fewshot_15min.list只引用train内清晰日常片段，不复制WAV，最多十五分钟；全量档案同样保留。
官方说明提示大量单语适配可能影响跨语言能力，因此同时交付全量与小集合，后续不要盲目假设全量或小集合一定更好。
当前main/wiki与发布整合包的版本不同；维护者版本表注明v5少样本适配尚未验证，使用前须固定具体仓库commit与底模。
上游依据和GitHub整理方法见各包RESEARCH.md及仓库docs/TTS_PREPARATION_RESEARCH.md。

## 清理和验证

按用户要求删除23个过期生成ZIP，详情和删除前SHA见AIlover_TTS_V1_旧包清理记录.json。
保留文本V3；V2中文文本仍是现有V3构建器的必要输入，未擅自删除。旧解压原材料与所有游戏原声、剧本、汉化均未改。
ZIP包含合格WAV、全部索引与排除记录、来源KS/hash、日文.list、中文目标、参考清单、说明和独立标准库校验器。
每包实际重新解压验证CRC、全文件SHA、源剧本物理行、角色/语种/转写、所有WAV帧、重复PCM、分区隔离和标签精确覆盖。
分角色临时验证目录核验后清理；主包解压结果保留，可直接作为后续训练机器上传材料。
'''
    report += f"\n复核旧冻结文件SHA {checks['legacy_frozen_file_hashes_rechecked']} 个，原始归档、Opus与文本V3均保持不变。\n\n|交付|字节数|SHA256|\n|---|---:|---|\n"
    for r in archives:
        report += f"|{r['file']}|{r['bytes']}|`{r['sha256']}`|\n"
    report += '\n复现：`.venv/Scripts/python.exe -B -X utf8 scripts/build_tts_preparation_v1.py --output finetune_data/tts_preparation_v1/新目录 --publish`。\n'
    report += '先 --analyze-only 可只做完整解码/来源缓存；相同输出目录的已完成音频分析可以复用，不再重复解码。\n'
    return report


def write_lists(root, slug, accepted, fewshot):
    for split in ('all', 'train', 'validation', 'test', 'fewshot_15min'):
        rows = accepted if split == 'all' else fewshot if split == 'fewshot_15min' else [r for r in accepted if r['split'] == split]
        destination = root / f'tts_adaptation/{slug}/labels/{split}.list'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(''.join(f'{r["audio_path"]}|{slug}|ja|{clean_ja(r["ja_text"])}\n' for r in rows), encoding='utf-8')


def archive_files(metadata_root, audio_map, roles):
    files = {p.relative_to(metadata_root).as_posix(): p for p in metadata_root.rglob('*')
             if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    files.update({name: source for name, source in audio_map.items() if name.split('/')[1] in roles})
    return files


def zip_package(metadata, audio_map, archive, roles):
    files = archive_files(metadata, audio_map, roles)
    manifest = {name: {'bytes': p.stat().st_size, 'sha256': sha(p)} for name, p in sorted(files.items())}
    json_write(metadata / 'manifest.json', {'algorithm': 'SHA256', 'files': manifest})
    files['manifest.json'] = metadata / 'manifest.json'
    with ZipFile(archive, 'x', ZIP_DEFLATED, compresslevel=1) as z:
        for count, (name, path) in enumerate(sorted(files.items()), 1):
            z.write(path, metadata.name + '/' + name)
            if count % 750 == 0:
                print(f'{archive.name}: written {count}/{len(files)} files', flush=True)
    return sha(archive)


def extracted_verify(archive, destination):
    from tts_preparation_verify import verify_package
    with ZipFile(archive) as z:
        print('Checking ZIP CRC: ' + archive.name, flush=True)
        if z.testzip():
            raise ValueError('ZIP CRC failed')
        names = z.namelist()
        if len(names) != len(set(names)) or any('..' in Path(n).parts or ':' in n or '\\' in n or n.startswith('/') for n in names):
            raise ValueError('Unsafe ZIP paths')
        z.extractall(destination)
    folder = destination / names[0].split('/')[0]
    print('Checking decoded files and source ledger: ' + archive.name, flush=True)
    verified = verify_package(folder)
    # Run the actual delivered tool, rather than only importing the repository copy.
    run = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(folder / 'tools/verify.py'), 'verify', '--root', str(folder)],
                         capture_output=True, text=True, encoding='utf-8')
    if run.returncode:
        raise ValueError('Delivered verification failed: ' + run.stdout[-2000:] + run.stderr[-2000:])
    return {'zip_crc': 'passed', 'extracted_repository_verifier': verified,
            'extracted_delivered_verifier': json.loads(run.stdout)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'finetune_data/tts_preparation_v1/20261023')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--analyze-only', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--resume-packaging', action='store_true', help='Recheck existing ZIPs and resume missing packages without overwriting')
    parser.add_argument('--package-build', default='delivery-01', help='Fresh packaging subdirectory; analysis cache is reused')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.package_build):
        raise ValueError('Invalid package build name')
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'finetune_data/tts_preparation_v1') or args.workers < 1 or args.workers > 16:
        raise ValueError('Use a V1 output directory inside finetune_data/tts_preparation_v1 and 1-16 workers')
    output.mkdir(parents=True, exist_ok=True)
    game = ROOT / '国王恋爱'
    archive = game / 'voice.xp3'
    source_inventory = {name: sha(game / name) for name in ('voice.xp3', 'data.xp3', 'patch.xp3')}
    occurrences, scripts = source_alignment(output, game)
    v3_lines, v3_packages, partition = read_v3()
    occurrences_index = {r['source_line_id']: r for r in occurrences}
    for ident, row in v3_lines.items():
        if occurrences_index[ident]['zh_text'] != row['source_text']:
            raise ValueError('V3 target differs from actual localization')
    rows_write(output / 'analysis/source_occurrences.jsonl', occurrences)
    json_write(output / 'analysis/source_inventory.json', {'archives': source_inventory, 'scripts': scripts,
               'text_v3': v3_packages, 'date': '2026-10-23'})
    entries = fast_xp3_index(archive)
    print(f'Actual archive entries={len(entries)}; source occurrences={len(occurrences)}; no reslicing needed', flush=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    analysis = analyze(entries, occurrences, output, archive, ffmpeg, args.workers)
    rows_write(output / 'analysis/audio_qc_sorted.jsonl', analysis)
    records = form_index(analysis, occurrences, partition)
    references, fewshot = choose_references_and_fewshot(records, v3_lines)
    rows_write(output / 'analysis/utterance_index.jsonl', records)
    json_write(output / 'analysis/preliminary_counts.json', {slug: {'raw': sum(r['character_id'] == slug for r in records),
        'accepted': sum(r['character_id'] == slug and r['audio_path_scope'] == 'package' for r in records),
        'reasons': dict(Counter(reason for r in records if r['character_id'] == slug for reason in r['quality_reasons'])),
        'fewshot': len(fewshot[slug]), 'references': references[slug]} for slug in ROLES})
    if args.analyze_only:
        print('Analysis complete; cached PCM metrics/WAV reuse ready. No package yet.', flush=True)
        return
    build_delivery(output, records, analysis, occurrences, scripts, source_inventory, v3_lines, v3_packages, references, fewshot, args.publish, args.package_build, args.resume_packaging)


if __name__ == '__main__':
    main()
