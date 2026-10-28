"""Portable, standard-library validation for AIlover TTS preparation packages.

This tool performs no training, inference, ASR, listening review, source deletion,
or in-package mutation. ``paths`` writes absolute-path copies outside the package.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import wave

CHARACTERS = {'hika', 'ayame', 'mugi'}
SPEAKERS = {'緋華': 'hika', '佐藤緋華': 'hika', '绯华': 'hika',
            '菖蒲': 'ayame', '藤ヶ丘菖蒲': 'ayame',
            'むぎ': 'mugi', '麦': 'mugi', '小麦': 'mugi'}
SPLITS = ('train', 'validation', 'test', 'reference')
LISTS = ('all', 'train', 'validation', 'test', 'fewshot_15min')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
TAG = re.compile(r'\[([^\]]+)\]')
SPAN = re.compile(r'\[>>\](.*?)\[<<\]', re.S)
CONTROL = {'if', 'else', 'elsif', 'endif', 'eval', 'c', 'r', 'hh',
           'layopt', 'jump', 'call', 'return', 'icHeart'}


def clean_ja(text):
    return re.sub(r'\s+', ' ', text.replace('|', ' ')).strip()


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def json_read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object)


def jsonl_read(path):
    return [json.loads(line, object_pairs_hook=unique_object)
            for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def safe_path(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Invalid package-relative path: ' + repr(relative))
    posix = PurePosixPath(relative)
    if posix.is_absolute() or '..' in posix.parts or posix.as_posix() != relative:
        raise ValueError('Unsafe or noncanonical relative path: ' + relative)
    result = root.joinpath(*posix.parts)
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path escapes package: ' + relative)
    current = root
    for part in posix.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('Package symlinks are not supported: ' + relative)
    return result


def source_decode(path):
    raw = path.read_bytes()
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            pass
    raise ValueError('Unsupported source encoding: ' + path.name)


def parse_source(path, relative_source):
    """Reconstruct the known KAG record identity without executing bundled Python."""
    records = []
    speaker, voice, label, pending, start = None, None, None, None, None

    def emit(body, first, last):
        nonlocal voice
        text = body.strip()
        if not text:
            return
        ordinal = sum(r['source_location']['line_start'] == first for r in records)
        ident = hashlib.sha256(f'{relative_source}:{first}:{last}:{ordinal}'.encode()).hexdigest()[:24]
        records.append({'source_line_id': ident, 'text': TAG.sub('', text).strip(),
                        'source_file': relative_source, 'source_location': {'line_start': first, 'line_end': last},
                        'character': SPEAKERS.get(speaker), 'speaker': speaker, 'voice_id': voice,
                        'source_scene_id': f'{relative_source}#{label}' if label else None})
        voice = None

    for number, raw in enumerate(source_decode(path).splitlines(), 1):
        line = raw.strip()
        if pending is not None:
            pending += '\n' + line
            if '[<<]' in line:
                emit(pending.split('[<<]', 1)[0], start, number)
                pending = None
            continue
        if not line or line.startswith(';'):
            continue
        if line.startswith('*'):
            label = line[1:].split('|', 1)[0].strip()
            speaker, voice = None, None
            continue
        command = line[1:].split()[0] if line.startswith('@') else None
        if command in ('if', 'elsif', 'else', 'endif') or re.match(r'\[(?:if|elsif|else|endif)(?:\s|\])', line):
            speaker, voice = None, None
            continue
        if line.startswith('@'):
            if re.search(r'jump|call|return|select|choice', command or '', re.I):
                speaker, voice = None, None
            continue
        match = TAG.match(line)
        if match and not line.startswith('[>>]'):
            tag = match[1]
            name = tag.split()[0]
            if name in CONTROL or not re.fullmatch(r'[^\s=\[\]>/]+', name) or (' ' in tag and 'vo=' not in tag):
                speaker, voice = None, None
                continue
            speaker = name
            found = re.search(r'\bvo=([\w-]+)', tag)
            voice = found[1] if found else None
            line = line[match.end():]
        matches = list(SPAN.finditer(line))
        if matches:
            for match in matches:
                emit(match[1], number, number)
        elif '[>>]' in line:
            pending, start = line.split('[>>]', 1)[1], number
        elif line and not line.startswith('['):
            emit(line, number, number)
    if pending is not None:
        raise ValueError('Unterminated source dialogue: ' + relative_source)
    return {r['source_line_id']: r for r in records}


def wav_info(path):
    pcm = hashlib.sha256()
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 32000, 'NONE'):
            raise ValueError('WAV must be uncompressed mono 32 kHz 16-bit PCM: ' + path.name)
        expected = audio.getnframes()
        count = 0
        while True:
            frames = audio.readframes(65536)
            if not frames:
                break
            if len(frames) % 2:
                raise ValueError('Truncated PCM sample: ' + path.name)
            count += len(frames) // 2
            pcm.update(frames)
        if count != expected or count == 0:
            raise ValueError('WAV frame count mismatch or empty audio: ' + path.name)
    return {'frames': count, 'duration_seconds': count / 32000, 'pcm_sha256': pcm.hexdigest(),
            'processed_audio_sha256': digest(path)}


def required(row, fields, label):
    missing = [field for field in fields if field not in row]
    if missing:
        raise ValueError(label + ' missing fields: ' + ', '.join(missing))


def verify(root):
    root = root.resolve()
    package = json_read(root / 'package.json')
    characters = package.get('characters')
    if not isinstance(characters, list) or not characters or len(set(characters)) != len(characters) or not set(characters) <= CHARACTERS:
        raise ValueError('package.json.characters must be unique supported slug strings')
    manifest = json_read(root / 'manifest.json').get('files')
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError('Empty or missing file manifest')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(manifest) | {'manifest.json'}:
        raise ValueError('Manifest coverage differs from package files: ' + repr(sorted(actual ^ (set(manifest) | {'manifest.json'}))[:15]))
    for relative, entry in manifest.items():
        path = safe_path(root, relative)
        if not isinstance(entry, dict) or entry.get('bytes') != path.stat().st_size or entry.get('sha256') != digest(path):
            raise ValueError('Manifest checksum mismatch: ' + relative)
    compressed_audio = {name for name in manifest if PurePosixPath(name).suffix.lower() in
                        ('.opus', '.ogg', '.mp3', '.flac', '.m4a', '.aac', '.wma')}
    if compressed_audio:
        raise ValueError('External original compressed audio must not be bundled: ' + repr(sorted(compressed_audio)[:10]))
    status = json_read(root / 'zh_supervised_data_status.json')
    if status.get('actual_chinese_recordings') != 0 or status.get('valid_zh_audio_text_pairs') != 0:
        raise ValueError('This Japanese-only preparation package must declare zero real Chinese audio/text pairs')
    occurrence_rows = jsonl_read(root / 'source/occurrences.jsonl')
    scene_variants_path = root / 'source/scene_label_variants.jsonl'
    scene_rows = jsonl_read(scene_variants_path) if scene_variants_path.exists() else []
    scene_variants = {r['source_line_id']: r for r in scene_rows}
    if len(scene_rows) != len(scene_variants):
        raise ValueError('Duplicate localized scene-label mapping')
    ledger, parsed, source_hashes = {}, {}, {}
    source_fields = ('source_line_id', 'voice_id', 'character', 'ja_text', 'zh_text', 'source_file',
                     'source_location', 'ja_script_sha256', 'zh_script_sha256', 'ja_speaker', 'zh_speaker')
    for occurrence in occurrence_rows:
        required(occurrence, source_fields, 'Source occurrence')
        ident, slug = occurrence['source_line_id'], occurrence['character']
        if ident in ledger or slug not in characters:
            raise ValueError('Duplicate source ID or unsupported source character: ' + str(ident))
        for language, field in [('ja', 'ja_script_sha256'), ('zh', 'zh_script_sha256')]:
            relative = occurrence['source_file']
            key = (language, relative)
            if key not in parsed:
                path = safe_path(root, 'source/' + language + '/' + relative)
                source_hashes[key] = digest(path)
                parsed[key] = parse_source(path, relative)
            if source_hashes[key] != occurrence[field]:
                raise ValueError('Source script SHA256 mismatch: ' + relative)
            found = parsed[key].get(ident)
            text_field, speaker_field = ('ja_text', 'ja_speaker') if language == 'ja' else ('zh_text', 'zh_speaker')
            if not found or any(found[k] != occurrence[k] for k in ('voice_id', 'character', 'source_file', 'source_location')):
                raise ValueError('Source line identity/character/voice differs from KS: ' + ident)
            if found['text'] != occurrence[text_field] or found['speaker'] != occurrence[speaker_field]:
                raise ValueError('Source transcript/speaker differs from KS: ' + ident)
            scene = occurrence.get('source_scene_id')
            mapping = scene_variants.get(ident)
            if mapping:
                if mapping.get('character') != slug:
                    raise ValueError('Localized scene mapping belongs to another character')
                if mapping['ja_source_scene_id'] != scene:
                    raise ValueError('Canonical Japanese scene label differs from mapping')
                scene = mapping[language + '_source_scene_id']
            if 'source_scene_id' in occurrence and scene != found['source_scene_id']:
                raise ValueError('Source scene differs from KS: ' + ident)
        ledger[ident] = occurrence
    if set(scene_variants) - set(ledger):
        raise ValueError('Localized scene mapping refers to unknown source IDs')
    index_rows = jsonl_read(root / 'alignment/index.jsonl')
    index = {}
    index_fields = ('utterance_id', 'character_id', 'audio_path', 'audio_path_scope', 'ja_text', 'zh_text',
                    'source_game_file', 'source_scene_id', 'source_line_id', 'audio_start', 'audio_end',
                    'audio_language', 'alignment_status', 'quality_status', 'review_status',
                    'speaker_confidence', 'transcript_confidence', 'source_occurrences')

    def check_occurrences(row, must_have_source):
        occurrences = row['source_occurrences']
        if not isinstance(occurrences, list) or (must_have_source and not occurrences):
            raise ValueError('Invalid/missing source occurrences: ' + row['utterance_id'])
        if len({o.get('source_line_id') for o in occurrences if isinstance(o, dict)}) != len(occurrences):
            raise ValueError('Repeated/invalid source occurrence: ' + row['utterance_id'])
        for occurrence in occurrences:
            required(occurrence, source_fields, 'Embedded source occurrence')
            master = ledger.get(occurrence['source_line_id'])
            if not master or any(occurrence[k] != master[k] for k in source_fields):
                raise ValueError('Embedded source occurrence differs from ledger: ' + row['utterance_id'])
            if occurrence['character'] != row['character_id']:
                raise ValueError('Cross-character source contamination: ' + row['utterance_id'])
        if occurrences:
            files = {o['source_file'] for o in occurrences}
            expected_file = next(iter(files)) if len(files) == 1 else None
            expected_scene = occurrences[0].get('source_scene_id') if len(occurrences) == 1 else None
            if row['source_line_id'] != occurrences[0]['source_line_id'] or row['source_game_file'] != expected_file or row['source_scene_id'] != expected_scene:
                raise ValueError('Primary source markers differ from source occurrences: ' + row['utterance_id'])
            if len({o['voice_id'] for o in occurrences}) != 1:
                raise ValueError('One utterance incorrectly merges different native voice IDs: ' + row['utterance_id'])
            if 'voice_id' in row and row['voice_id'] != occurrences[0]['voice_id']:
                raise ValueError('Native voice ID differs from source occurrence: ' + row['utterance_id'])
            ja_variants = {clean_ja(o['ja_text']) for o in occurrences if clean_ja(o['ja_text'])}
            zh_variants = {o['zh_text'] for o in occurrences if o['zh_text'].strip()}
            if len(ja_variants) == 1:
                if not isinstance(row['ja_text'], str) or clean_ja(row['ja_text']) != next(iter(ja_variants)):
                    raise ValueError('Alignment JA text differs from source: ' + row['utterance_id'])
            elif row['ja_text'] is not None:
                raise ValueError('Ambiguous JA source transcripts were collapsed: ' + row['utterance_id'])
            if row['zh_text'] != (next(iter(zh_variants)) if len(zh_variants) == 1 else None):
                raise ValueError('Alignment ZH text collapses variants or differs from source: ' + row['utterance_id'])
        elif any(row[k] is not None for k in ('source_line_id', 'source_game_file', 'source_scene_id')):
            raise ValueError('Unmapped audio fabricates primary source markers: ' + row['utterance_id'])

    for row in index_rows:
        required(row, index_fields, 'Raw alignment')
        ident = row['utterance_id']
        if not isinstance(ident, str) or not ident or ident in index or row['character_id'] not in characters:
            raise ValueError('Duplicate/invalid utterance or character in raw index')
        if row['audio_language'] != 'ja' or row['audio_path_scope'] not in ('package', 'external'):
            raise ValueError('Unexpected audio language/scope: ' + ident)
        if row['audio_path_scope'] == 'package':
            safe_path(root, row['audio_path'])
        check_occurrences(row, False)
        index[ident] = row
    accepted_all, pcm_seen, groups, counts = {}, {}, {}, {}
    for slug in characters:
        folder = root / 'tts_adaptation' / slug
        accepted = jsonl_read(folder / 'accepted.jsonl')
        excluded = jsonl_read(folder / 'excluded.jsonl')
        accepted_by_id, expected, audio_infos = {}, {name: [] for name in LISTS}, {}
        for row in accepted:
            required(row, index_fields + ('processed_audio_sha256', 'pcm_sha256', 'duration_seconds',
                                          'split', 'partition_group', 'partition_group_split'), 'Accepted utterance')
            ident = row['utterance_id']
            original = index.get(ident)
            if ident in accepted_all or not original or row['character_id'] != slug or original['character_id'] != slug:
                raise ValueError('Accepted utterance missing from raw index, duplicated, or wrong character: ' + ident)
            check_occurrences(row, True)
            if {o['source_line_id'] for o in row['source_occurrences']} != {o['source_line_id'] for o in original['source_occurrences']}:
                raise ValueError('Accepted source identity differs from raw alignment: ' + ident)
            if original['audio_path_scope'] == 'package' and original['audio_path'] != row['audio_path']:
                raise ValueError('Accepted package audio path differs from raw index: ' + ident)
            if row['audio_language'] != 'ja' or row['audio_path_scope'] != 'package':
                raise ValueError('Accepted audio must be local package Japanese audio: ' + ident)
            source_ja = {clean_ja(o['ja_text']) for o in row['source_occurrences']}
            if len(source_ja) != 1 or clean_ja(row['ja_text']) not in source_ja or not clean_ja(row['ja_text']):
                raise ValueError('Accepted JA transcript is ambiguous or differs from original JA: ' + ident)
            if not isinstance(row['audio_start'], (int, float)) or not isinstance(row['audio_end'], (int, float)) or not math.isfinite(row['audio_start']) or not math.isfinite(row['audio_end']) or row['audio_start'] < 0 or row['audio_end'] <= row['audio_start']:
                raise ValueError('Invalid accepted audio bounds: ' + ident)
            path = safe_path(root, row['audio_path'])
            info = wav_info(path)
            audio_infos[ident] = info
            for field in ('processed_audio_sha256', 'pcm_sha256'):
                if not isinstance(row[field], str) or not SHA256.fullmatch(row[field]) or row[field] != info[field]:
                    raise ValueError('Audio checksum mismatch: ' + ident + ':' + field)
            if not isinstance(row['duration_seconds'], (int, float)) or not math.isfinite(row['duration_seconds']) or abs(row['duration_seconds'] - info['duration_seconds']) > 1 / 32000:
                raise ValueError('Audio duration differs from readable PCM: ' + ident)
            if info['pcm_sha256'] in pcm_seen:
                raise ValueError('Duplicate accepted PCM: ' + ident + ' and ' + pcm_seen[info['pcm_sha256']])
            pcm_seen[info['pcm_sha256']] = ident
            split, group_split, group = row['split'], row['partition_group_split'], row['partition_group']
            if split not in SPLITS or group_split not in SPLITS[:3] or not isinstance(group, str) or not group.endswith('.ks'):
                raise ValueError('Invalid split/group: ' + ident)
            if split == 'reference' and group_split != 'train' or split != 'reference' and split != group_split:
                raise ValueError('Reference/group split inconsistency: ' + ident)
            source_files = {o['source_file'] for o in row['source_occurrences']}
            if len(source_files) != 1 or group not in source_files:
                raise ValueError('Partition group does not identify all source occurrences: ' + ident)
            if group in groups and groups[group] != group_split:
                raise ValueError('Source script group leaks across partitions: ' + group)
            groups[group] = group_split
            line = f"{row['audio_path']}|{slug}|ja|{clean_ja(row['ja_text'])}"
            expected['all'].append(line)
            if split != 'reference':
                expected[split].append(line)
            accepted_by_id[ident] = row
            accepted_all[ident] = row
        excluded_ids = set()
        for row in excluded:
            required(row, ('utterance_id', 'character_id', 'quality_reasons'), 'Excluded utterance')
            ident = row['utterance_id']
            if ident in excluded_ids or ident in accepted_all or ident not in index or row['character_id'] != slug or not row['quality_reasons']:
                raise ValueError('Invalid excluded utterance or missing reasons: ' + str(ident))
            excluded_ids.add(ident)
        raw_ids = {ident for ident, r in index.items() if r['character_id'] == slug}
        if raw_ids != set(accepted_by_id) | excluded_ids:
            raise ValueError('Accepted/excluded do not partition all raw utterances for ' + slug)
        label_rows = {}
        for name in LISTS:
            path = folder / 'labels' / (name + '.list')
            lines = [line for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
            if len(lines) != len(set(lines)):
                raise ValueError('Duplicate label rows: ' + slug + ':' + name)
            label_rows[name] = lines
            for line in lines:
                fields = line.split('|')
                if len(fields) != 4 or fields[1:3] != [slug, 'ja'] or not fields[3]:
                    raise ValueError('Invalid GPT-SoVITS label: ' + slug + ':' + name)
                safe_path(root, fields[0])
            if name != 'fewshot_15min' and Counter(lines) != Counter(expected[name]):
                raise ValueError('Labels differ from accepted data: ' + slug + ':' + name)
        if not set(label_rows['fewshot_15min']) <= set(label_rows['train']):
            raise ValueError('Few-shot labels include non-training data: ' + slug)
        fewshot_paths = {line.split('|', 1)[0] for line in label_rows['fewshot_15min']}
        fewshot_seconds = sum(audio_infos[ident]['duration_seconds'] for ident, r in accepted_by_id.items() if r['audio_path'] in fewshot_paths)
        if fewshot_seconds > 900 + 1 / 32000:
            raise ValueError('Few-shot selection exceeds 15 minutes: ' + slug)
        references = json_read(root / 'references' / (slug + '.json'))
        if not isinstance(references, list):
            raise ValueError('References must be an array: ' + slug)
        reference_ids = []
        for reference in references:
            required(reference, ('utterance_id', 'audio_path', 'ja_text'), 'Reference')
            ident = reference['utterance_id']
            row = accepted_by_id.get(ident)
            if not row or row['split'] != 'reference' or reference['audio_path'] != row['audio_path'] or clean_ja(reference['ja_text']) != clean_ja(row['ja_text']):
                raise ValueError('Reference differs from accepted reference audio: ' + str(ident))
            reference_ids.append(ident)
        if len(reference_ids) != len(set(reference_ids)) or set(reference_ids) != {i for i, r in accepted_by_id.items() if r['split'] == 'reference'}:
            raise ValueError('Reference registry does not exactly cover reference split: ' + slug)
        cross_rows = jsonl_read(root / 'crosslingual_alignment' / (slug + '.jsonl'))
        cross_ids = set()
        for row in cross_rows:
            required(row, ('utterance_id', 'zh_text'), 'Crosslingual alignment')
            ident = row['utterance_id']
            original = index.get(ident)
            if ident in cross_ids or not original or original['character_id'] != slug:
                raise ValueError('Duplicate/unknown crosslingual utterance: ' + str(ident))
            variants = {o['zh_text'] for o in original['source_occurrences'] if isinstance(o['zh_text'], str) and o['zh_text'].strip()}
            if not variants or (len(variants) == 1 and row['zh_text'] != next(iter(variants))):
                raise ValueError('Crosslingual localized text differs from source: ' + str(ident))
            if len(variants) > 1:
                supplied = row.get('zh_variants', [])
                if not isinstance(supplied, list) or not all(isinstance(item, dict) for item in supplied):
                    raise ValueError('Localized variants must retain their source line IDs: ' + str(ident))
                expected_variants = {text: {o['source_line_id'] for o in original['source_occurrences'] if o['zh_text'] == text} for text in variants}
                actual_variants = {item.get('zh_text'): set(item.get('source_line_ids', [])) for item in supplied}
                if row['zh_text'] is not None or len(supplied) != len(expected_variants) or actual_variants != expected_variants:
                    raise ValueError('Multiple localized variants were silently collapsed or lost source IDs: ' + str(ident))
            cross_ids.add(ident)
        target_keys = set()
        for row in jsonl_read(root / 'zh_target_text' / (slug + '.jsonl')):
            required(row, ('source_line_id', 'utterance_id', 'zh_text'), 'Chinese target text')
            source, original = ledger.get(row['source_line_id']), index.get(row['utterance_id'])
            key = (row['source_line_id'], row['utterance_id'])
            if key in target_keys or not source or source['character'] != slug or not original or original['character_id'] != slug or row['zh_text'] != source['zh_text'] or not any(o['source_line_id'] == row['source_line_id'] for o in original['source_occurrences']):
                raise ValueError('Chinese target text lost its exact source/utterance link')
            target_keys.add(key)
        counts[slug] = {'raw_utterances': len(raw_ids), 'accepted': len(accepted), 'excluded': len(excluded),
                        'splits': dict(Counter(r['split'] for r in accepted)),
                        'accepted_duration_seconds': round(sum(i['duration_seconds'] for i in audio_infos.values()), 6),
                        'fewshot_duration_seconds': round(fewshot_seconds, 6), 'references': len(references),
                        'crosslingual_records': len(cross_rows), 'zh_target_records': len(target_keys)}
    packaged_wavs = {name for name in manifest if PurePosixPath(name).suffix.lower() == '.wav'}
    if packaged_wavs != {row['audio_path'] for row in accepted_all.values()}:
        raise ValueError('Packaged WAVs must exactly equal accepted audio; references reuse those files')
    return {'status': 'passed', 'characters': characters, 'verified_manifest_files': len(manifest),
            'verified_source_occurrences': len(ledger), 'verified_source_scripts': len(parsed),
            'counts': counts, 'actual_chinese_recordings': 0, 'valid_zh_audio_text_pairs': 0,
            'audio_validation': 'All accepted WAV frames read; PCM format, duration, file/PCM SHA256 and duplicate PCM checked.',
            'not_measured': ['listening_transcript_accuracy', 'BGM_detection', 'overlapping_speakers',
                             'voice_similarity', 'naturalness', 'trained_model_quality'],
            'package_inputs_modified': False}


def absolute_paths(root, character, output_dir):
    result = verify(root)
    if character not in result['characters']:
        raise ValueError('Character is not in this package: ' + character)
    destination = output_dir if output_dir else root.parent / (root.name + '_absolute_paths')
    if not destination.is_absolute():
        raise ValueError('--output-dir must be absolute')
    destination = destination.resolve()
    if destination.is_relative_to(root.resolve()):
        raise ValueError('Absolute-path output must be outside the manifest-controlled package')
    destination.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name in LISTS:
        path = root / 'tts_adaptation' / character / 'labels' / (name + '.list')
        converted = []
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip():
                continue
            relative, slug, language, text = line.split('|')
            absolute = safe_path(root, relative).resolve().as_posix()
            converted.append('|'.join((absolute, slug, language, text)))
        output = destination / (character + '_' + name + '.list')
        output.write_text(''.join(line + '\n' for line in converted), encoding='utf-8')
        outputs.append(str(output))
    return {'status': 'passed', 'character': character, 'output_files': outputs,
            'package_inputs_modified': False, 'verification': result}


verify_package = verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('verify', help='Verify an extracted package without modifying it')
    check.add_argument('--root', type=Path, required=True)
    paths = commands.add_parser('paths', help='Create absolute label copies outside the package')
    paths.add_argument('--root', type=Path, required=True)
    paths.add_argument('--character', choices=sorted(CHARACTERS), required=True)
    paths.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        result = verify(root) if args.command == 'verify' else absolute_paths(root, args.character, args.output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, wave.Error, EOFError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error), 'package_inputs_modified': False}, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
