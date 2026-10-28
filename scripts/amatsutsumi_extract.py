"""Read-only CMVS / Amatsutsumi source extraction and independent PS3 parsing.

PS2A decrypt/LZSS follows GARbro ArcCPZ.cs (MIT, morkt, 2015-2019)
and xmoezzz/CMVS-Engine Ps2TextDumper (MIT). PKP directory structure
is checked against this user's actual patch archive, never executed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / '[無碼] 天津罪（アマツツミ）'
OUTPUT = ROOT / 'extracted/amatsutsumi'


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def unpack_ps2(data, encrypted=True):
    """Return exact decoded PS2A header/body; refuse truncation and bad backrefs."""
    if len(data) < 0x30 or data[:4] != b'PS2A':
        raise ValueError('Not PS2A')
    header = struct.unpack_from('<12I', data)
    if header[1] != 0x30 or header[10] > 100_000_000:
        raise ValueError('PS2A size/header out of range')
    # GARbro extraction returns a decoded body with the original packed header.
    # Size is a reliable discriminator for source files in this game.
    if len(data) == 0x30 + header[10]:
        return bytes(data)
    if len(data) != 0x30 + header[9]:
        raise ValueError('Truncated PS2A packed body')
    key = header[3]
    shift = (key >> 20) % 5 + 1
    xor = ((key >> 24) + (key >> 3)) & 255
    source = bytearray(data[0x30:])
    if encrypted:
        for i, value in enumerate(source):
            value = ((value - 0x7c) & 255) ^ xor
            source[i] = ((value >> shift) | (value << (8 - shift))) & 255
    frame = bytearray(0x800)
    frame_pos, position, control = 0x7df, 0, 1
    target = bytearray()
    while len(target) < header[10]:
        if control == 1:
            if position >= len(source):
                raise ValueError('Truncated PS2A control')
            control = source[position] | 0x100
            position += 1
        if control & 1:
            if position >= len(source):
                raise ValueError('Truncated PS2A literal')
            values = [source[position]]
            position += 1
        else:
            if position + 2 > len(source):
                raise ValueError('Truncated PS2A backreference')
            lo, hi = source[position:position + 2]
            position += 2
            offset, count = lo | ((hi & 0xe0) << 3), (hi & 0x1f) + 2
            values = None
        if values is not None:
            for value in values:
                target.append(value)
                frame[frame_pos] = value
                frame_pos = (frame_pos + 1) & 0x7ff
        else:
            for step in range(count):
                if len(target) >= header[10]:
                    raise ValueError('PS2A backreference overshoots output')
                value = frame[(offset + step) & 0x7ff]
                target.append(value)
                frame[frame_pos] = value
                frame_pos = (frame_pos + 1) & 0x7ff
        control >>= 1
    return data[:0x30] + bytes(target)


def pkp_index(path):
    with Path(path).open('rb') as handle:
        head = handle.read(12)
        if head[:4] != b'PKP\0':
            raise ValueError('Not PKP')
        count = struct.unpack_from('<I', head, 8)[0]
        if not 0 < count < 100_000:
            raise ValueError('PKP count out of range')
        data = handle.read(count * 176)
    if len(data) != count * 176:
        raise ValueError('Truncated PKP index')
    rows, names = [], set()
    size = Path(path).stat().st_size
    for number in range(count):
        item = data[number * 176:(number + 1) * 176]
        offset, unpacked, packed = struct.unpack_from('<III', item)
        name = item[0x30:].decode('utf-16-le').split('\0', 1)[0]
        if not name or Path(name).name != name or name in names or offset < 12 + count * 176 or offset + packed > size:
            raise ValueError('Invalid PKP entry')
        names.add(name)
        rows.append({'archive_entry': name, 'archive_index': number, 'offset': offset,
                     'packed_size': packed, 'unpacked_size': unpacked})
    return rows


def extract_pkp(path, out):
    rows = pkp_index(path)
    archive_sha = sha(path)
    out.mkdir(parents=True, exist_ok=True)
    with path.open('rb') as handle:
        for row in rows:
            handle.seek(row['offset'])
            raw = handle.read(row['packed_size'])
            member = zlib.decompress(raw, -15)
            if len(member) != row['unpacked_size']:
                raise ValueError('PKP decoded member length mismatch')
            # This localization's PKP members keep LZSS but omit the normal
            # per-PS2A encryption, as verified by exact bounds/string decoding.
            decoded = unpack_ps2(member, encrypted=False) if member[:4] == b'PS2A' else member
            destination = out / row['archive_entry']
            if destination.exists() and destination.read_bytes() != decoded:
                raise ValueError('Refusing to overwrite a different decoded source')
            destination.write_bytes(decoded)
            row.update({'archive_path': str(path.relative_to(ROOT)), 'archive_sha256': archive_sha,
                        'compressed_member_sha256': hashlib.sha256(raw).hexdigest(),
                        'member_sha256': hashlib.sha256(member).hexdigest(),
                        'decoded_sha256': hashlib.sha256(decoded).hexdigest(),
                        'decoded_path': str(destination.relative_to(ROOT)).replace('\\', '/')})
    return rows


def ps3_structure(data):
    if len(data) < 48 or data[:4] != b'PS2A':
        raise ValueError('Not decoded PS3/PS2A')
    h = struct.unpack_from('<12I', data)
    code_start = 0x30 + h[4] * 4
    strings_start = code_start + h[5]
    if h[1] != 48 or len(data) != 48 + h[10] or strings_start + h[7] > len(data):
        raise ValueError('Bad decoded PS3 bounds')
    return {'code_start': code_start, 'code_end': strings_start,
            'strings_start': strings_start, 'strings_end': strings_start + h[7],
            'jump_count': h[4]}


def ps3_strings(data, encoding):
    layout = ps3_structure(data)
    rows = []
    pos = layout['strings_start']
    while pos < layout['strings_end']:
        end = data.find(b'\0', pos, layout['strings_end'])
        if end < 0:
            raise ValueError('Unterminated PS3 string')
        text = data[pos:end].decode(encoding, errors='strict')
        rows.append({'string_offset': pos, 'string_id': pos - layout['strings_start'], 'text': text,
                     'raw_hex': data[pos:end].hex()})
        pos = end + 1
    return rows


SEPARATOR = bytes.fromhex('0f023004')
STRING_PUSH = bytes.fromhex('01022001')
INT_PUSH = bytes.fromhex('00020001')
DIALOGUE_CALL = re.compile(b''.join([re.escape(STRING_PUSH) + b'(.{4})' + re.escape(SEPARATOR)] * 3
                                  + [re.escape(INT_PUSH) + b'(.{4})' + re.escape(SEPARATOR)] * 4)
                          + re.escape(bytes.fromhex('10044300')), re.S)
SPECIAL_DIALOGUE_CALL = re.compile(b''.join([re.escape(STRING_PUSH) + b'(.{4})' + re.escape(SEPARATOR)] * 3
                                          + [re.escape(INT_PUSH) + b'(.{4})' + re.escape(SEPARATOR)] * 2)
                                  + bytes.fromhex('1004') + b'([\x40\x42])' + b'\0', re.S)
RUBY = re.compile(r'\{([^{}]*)/([^{}]*)\}')
EXPLICIT = re.compile(r'性交|セックス|射精|精液|性器|膣|乳首|勃起|フェラ|パイズリ|アナル|中出し|ちんぽ|ちんこ|まんこ|オナニー|肉棒|陰茎|阴茎|阴道|乳头|精液|射精|口交|肛交|交配|内射|性爱|性欲|自慰|高潮|肉棒|强奸|強姦|パンツ|おっぱい|愛液|爱液')
LOCALIZED_SPEAKER_NAMES = {
    '誠': '诚', '？？？': '？？？', 'こころ': '心', 'あずき': '杏月', '愛': '爱',
    '男': '男', 'ほたる': '萤', '教師': '老师', '光一': '光一', '響子': '响子',
    '母': '母', '男子': '男生', '鈴夏': '铃夏', '希': '希', '子ども': '小孩',
    '母猫': '母猫', '子猫': '小猫', 'ＯＲほたる': '“萤”',
}


def speaker_conflict(japanese, chinese):
    ja = re.sub(r'\s+', '', japanese or '')
    zh = re.sub(r'\s+', '', chinese or '')
    expected = LOCALIZED_SPEAKER_NAMES.get(ja, ja)
    return zh != expected


def plain_text(text, japanese=False):
    def ruby(match):
        base, reading = match.groups()
        # Dot furigana is emphasis, not a reading. Real ruby is spoken from
        # the reading side while visible Chinese target text keeps the base.
        return reading if japanese and reading.strip('・.．●○') else base
    text = RUBY.sub(ruby, text)
    text = text.replace('\\n', ' ').replace('\\r', ' ')
    if len(text) > 1 and text[0] == '「' and text[-1] == '」':
        text = text[1:-1]
    return text.strip()


def parse_dialogue(path, encoding='cp932'):
    """Parse exact 7-argument CMVS message calls, not adjacent text guesses.

    Blocks contain only consecutive message instructions. Any intervening
    bytecode creates a fence, so preceding rows cannot cross an unknown jump.
    """
    data = Path(path).read_bytes()
    layout = ps3_structure(data)
    rows, previous_end, block = [], None, -1
    calls = [(match, '43') for match in DIALOGUE_CALL.finditer(data, layout['code_start'], layout['code_end'])]
    calls += [(match, match.group(6).hex()) for match in SPECIAL_DIALOGUE_CALL.finditer(data, layout['code_start'], layout['code_end'])]
    calls.sort(key=lambda pair: pair[0].start())
    for sequence, (match, call_kind) in enumerate(calls):
        parts = match.groups() if call_kind == '43' else match.groups()[:5]
        values = [struct.unpack('<I', part)[0] for part in parts]
        strings = []
        for relative in values[:3]:
            absolute = layout['strings_start'] + relative
            if absolute < layout['strings_start'] or absolute >= layout['strings_end'] or (relative and data[absolute - 1] != 0):
                raise ValueError('PS3 message string reference is not a string boundary')
            end = data.find(b'\0', absolute, layout['strings_end'])
            if end < 0:
                raise ValueError('PS3 message string unterminated')
            raw = data[absolute:end]
            try:
                text = raw.decode(encoding)
                decoding = encoding
            except UnicodeDecodeError:
                # Localized PS3 keeps unused Japanese original strings. A
                # fallback is recorded explicitly; it is not called Chinese.
                if encoding != 'gbk':
                    raise
                text, decoding = raw.decode('cp932'), 'cp932_untranslated_fallback'
            strings.append({'text': text, 'offset': absolute, 'id': relative, 'raw_hex': raw.hex(), 'encoding': decoding})
        if match.start() != previous_end:
            block += 1
        rows.append({'sequence': sequence, 'opcode_offset': match.start(), 'opcode_end': match.end(),
                     'message_id': values[-1], 'speaker_index': values[-2], 'parameters': values[3:], 'call_kind': call_kind,
                     'raw_text': strings[0]['text'], 'voice_filename': strings[1]['text'],
                     'voice_id': Path(strings[1]['text']).stem if strings[1]['text'] else None,
                     'speaker': strings[2]['text'].strip('　 '), 'strings': strings,
                     'segment': block, 'gap_before_bytes': match.start() - previous_end if previous_end else None})
        previous_end = match.end()
    return rows


def source_file_map(language):
    candidates = {}
    for level in ('base', 'update'):
        for path in sorted((OUTPUT / 'source' / language / level).rglob('sn*.ps3')):
            if path.name in candidates and level != 'update':
                raise ValueError('Duplicate source filename')
            candidates[path.name] = path
    return candidates


def align_sources():
    ja_paths, zh_paths = source_file_map('ja'), source_file_map('zh')
    all_rows, audit, script_inventory = [], [], []
    for filename, ja in sorted(ja_paths.items()):
        zh = zh_paths.get(filename)
        japanese, chinese = parse_dialogue(ja), parse_dialogue(zh, 'gbk') if zh else []
        ja_sha, zh_sha = sha(ja), sha(zh) if zh else None
        script_inventory.append({'source_file': filename, 'ja_path': ja.relative_to(ROOT).as_posix(),
                                 'zh_path': zh.relative_to(ROOT).as_posix() if zh else None,
                                 'ja_sha256': ja_sha, 'zh_sha256': zh_sha,
                                 'ja_messages': len(japanese), 'zh_messages': len(chinese)})
        by_identity = {}
        for row in chinese:
            identity = (row['message_id'], tuple(row['parameters']), row['voice_filename'], row['call_kind'])
            by_identity.setdefault(identity, []).append(row)
        for row in japanese:
            identity = (row['message_id'], tuple(row['parameters']), row['voice_filename'], row['call_kind'])
            matches = by_identity.get(identity, [])
            translated = matches[0] if len(matches) == 1 else None
            if len(matches) != 1:
                audit.append({'source_file': filename, 'ja_opcode_offset': row['opcode_offset'],
                              'message_id': row['message_id'], 'reason': 'missing_or_ambiguous_exact_structural_zh_match',
                              'candidates': len(matches)})
            voice = row['voice_id']
            slug = 'hotaru' if row['speaker_index'] == 4 and (row['speaker'] == 'ほたる' or (voice and voice.startswith('hosn'))) else row['speaker'] or 'narrator'
            ident = 'amatsutsumi_' + hashlib.sha256(f'{filename}:{row["message_id"]}:{row["sequence"]}'.encode()).hexdigest()[:24]
            zh_raw = translated['raw_text'] if translated else None
            zh_text = plain_text(zh_raw) if zh_raw is not None else None
            if translated and translated['strings'][0]['raw_hex'] == row['strings'][0]['raw_hex'] and re.search('[ぁ-ヿ一-鿿]', row['raw_text']):
                zh_text = None
            record = {'id': ident, 'source_line_id': ident, 'source_file': filename,
                      'source_sha256': ja_sha, 'source_location': f'opcode:0x{row["opcode_offset"]:x};message:{row["message_id"]}',
                      'scene_id': filename + '#linear_block_' + str(row['segment']),
                      'source_scene_id': filename + '#linear_block_' + str(row['segment']),
                      'segment': row['segment'], 'sequence': row['sequence'], 'route_id': None,
                      'speaker': row['speaker'], 'character': slug, 'voice_id': voice,
                      'ja_text': plain_text(row['raw_text'], japanese=True), 'zh_text': zh_text,
                      'ja_raw_text': row['raw_text'], 'zh_raw_text': zh_raw,
                      'alignment_status': 'confirmed' if translated else 'unresolved',
                      'alignment_basis': 'same source filename + message_id + all integer arguments + exact voice filename; no semantic matching',
                      'evidence_type': 'dialogue' if row['speaker'] else 'narration',
                      'ja_source_path': 'source/ja/' + filename, 'zh_source_path': 'source/zh/' + filename if zh else None,
                      'ja_source_repo_path': ja.relative_to(ROOT).as_posix(),
                      'zh_source_repo_path': zh.relative_to(ROOT).as_posix() if zh else None,
                      'ja_source_sha256': ja_sha, 'zh_source_sha256': zh_sha,
                      'ja_opcode_offset': row['opcode_offset'], 'zh_opcode_offset': translated['opcode_offset'] if translated else None,
                      'message_id': row['message_id'], 'speaker_index': row['speaker_index'],
                      'call_kind': row['call_kind'],
                      'ja_string_offset': row['strings'][0]['offset'], 'zh_string_offset': translated['strings'][0]['offset'] if translated else None,
                      'ja_voice_filename': row['voice_filename'], 'zh_voice_filename': translated['voice_filename'] if translated else None,
                      'zh_speaker_raw': translated['speaker'] if translated else None,
                      'localized_speaker_conflict': speaker_conflict(row['speaker'], translated['speaker']) if translated else True,
                      'branch_uncertain': False, 'context_fence_method': 'only consecutive message bytecode; every non-message gap starts a new segment',
                      'translation_source': 'local game Chinese PKP base + Scriptspk.UPD override' if translated else None,
                      'translation_review_status': 'unchanged_source_bytes_requires_review' if translated and translated['strings'][0]['raw_hex'] == row['strings'][0]['raw_hex'] else 'game_localization_pending_semantic_review',
                      'transcript_confidence': 'original_game_script_linked_not_listening_certified', 'review_status': 'pending_human'}
            all_rows.append(record)
    blocks = {}
    for row in all_rows:
        key = (row['source_file'], row['segment'])
        blocks.setdefault(key, []).append(row)
    for own in blocks.values():
        explicit = any(EXPLICIT.search((row['ja_raw_text'] or '') + '\n' + (row['zh_raw_text'] or '')) for row in own)
        for row in own:
            row['scene_safety'] = 'explicit' if explicit else 'safe_screened'
            row['scene_safety_method'] = 'automatic explicit keyword screen of entire linear block; not human rating'
    write_rows(OUTPUT / 'source/aligned_records.jsonl', all_rows)
    write_rows(OUTPUT / 'source/alignment_issues.jsonl', audit)
    write_rows(OUTPUT / 'source/scripts_inventory.jsonl', script_inventory)
    print(json.dumps({'all_dialogue_records': len(all_rows), 'hotaru_occurrences': sum(r['character'] == 'hotaru' for r in all_rows),
                      'structural_zh_matches': sum(r['alignment_status'] == 'confirmed' for r in all_rows),
                      'unresolved': len(audit)}, ensure_ascii=False), flush=True)
    return all_rows


def copy_package_sources(source_dir, package_root, rows):
    """Copy only exact source members required by supplied records, never models."""
    package_root = Path(package_root)
    copied = {}
    for row in rows:
        for language in ('ja', 'zh'):
            relative = row.get(language + '_source_path')
            original = row.get(language + '_source_repo_path')
            if not relative or not original:
                continue
            destination = (package_root / relative).resolve()
            if not destination.is_relative_to(package_root.resolve() / 'source'):
                raise ValueError('Unsafe source copy target')
            digest = row[language + '_source_sha256']
            if relative in copied:
                if copied[relative] != digest:
                    raise ValueError('Same source path has conflicting hashes')
                continue
            path = ROOT / original
            if sha(path) != digest:
                raise ValueError('Original source changed before packaging')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            copied[relative] = digest
    provenance = Path(source_dir) / 'source_inventory.json'
    if provenance.exists():
        shutil.copyfile(provenance, package_root / 'source/source_inventory.json')
    license_path = ROOT / 'docs/AMATSUTSUMI_SOURCE_READER.md'
    if license_path.exists():
        shutil.copyfile(license_path, package_root / 'source/READER_PROVENANCE.md')
    return copied


def verify_ledger(package_root, rows):
    """Independent reconstruction of every supplied source offset and label."""
    package_root = Path(package_root).resolve()
    parsed, source_hashes, count, supplied = {}, {}, 0, {}
    for row in rows:
        originals = {}
        for language, encoding in [('ja', 'cp932'), ('zh', 'gbk')]:
            relative = row.get(language + '_source_path')
            if not relative:
                continue
            path = (package_root / relative).resolve()
            if not path.is_relative_to(package_root / 'source'):
                raise ValueError('Unsafe ledger source path')
            if relative not in parsed:
                source_hashes[relative] = sha(path)
                parsed[relative] = {r['opcode_offset']: r for r in parse_dialogue(path, encoding)}
            if source_hashes[relative] != row[language + '_source_sha256']:
                raise ValueError('Ledger source file SHA mismatch')
            offset = row.get(language + '_opcode_offset')
            if offset is None:
                continue
            original = parsed[relative].get(offset)
            if not original or original['message_id'] != row['message_id'] or original['speaker_index'] != row['speaker_index']:
                raise ValueError('Ledger source opcode/speaker identity mismatch')
            if original['raw_text'] != row[language + '_raw_text'] or original['strings'][0]['offset'] != row[language + '_string_offset']:
                raise ValueError('Ledger raw source transcript mismatch')
            if original['voice_filename'] != row[language + '_voice_filename']:
                raise ValueError('Ledger original voice filename mismatch')
            originals[language] = original
        ja = originals.get('ja')
        if not ja or ja['speaker'] != row['speaker'] or ja['voice_id'] != row['voice_id'] or plain_text(ja['raw_text'], True) != row['ja_text']:
            raise ValueError('Ledger Japanese speaker/text mismatch')
        expected_id = 'amatsutsumi_' + hashlib.sha256(f'{row["source_file"]}:{ja["message_id"]}:{ja["sequence"]}'.encode()).hexdigest()[:24]
        if row['id'] != expected_id or row['source_line_id'] != expected_id or row['sequence'] != ja['sequence'] or row['segment'] != ja['segment']:
            raise ValueError('Ledger stable source identity/linear segment mismatch')
        if row['source_sha256'] != row['ja_source_sha256'] or Path(row['ja_source_path']).name != row['source_file']:
            raise ValueError('Ledger canonical source reference mismatch')
        seen = supplied.setdefault(row['ja_source_path'], set())
        if row['ja_opcode_offset'] in seen:
            raise ValueError('Duplicate ledger source opcode')
        seen.add(row['ja_opcode_offset'])
        scene = row['source_file'] + '#linear_block_' + str(ja['segment'])
        if row['scene_id'] != scene or row['source_scene_id'] != scene or row['branch_uncertain']:
            raise ValueError('Ledger source scene/branch boundary mismatch')
        if row['evidence_type'] != ('dialogue' if ja['speaker'] else 'narration'):
            raise ValueError('Ledger dialogue/narration type mismatch')
        expected_slug = 'hotaru' if ja['speaker_index'] == 4 and (ja['speaker'] == 'ほたる' or (ja['voice_id'] and ja['voice_id'].startswith('hosn'))) else ja['speaker'] or 'narrator'
        if row['character'] != expected_slug:
            raise ValueError('Ledger character identity mismatch')
        zh = originals.get('zh')
        if row['alignment_status'] == 'confirmed':
            if not zh or ja['parameters'] != zh['parameters'] or ja['voice_filename'] != zh['voice_filename'] or ja['call_kind'] != zh['call_kind'] or row['call_kind'] != ja['call_kind']:
                raise ValueError('Ledger bilingual structure mismatch')
            if row['zh_speaker_raw'] != zh['speaker'] or row['localized_speaker_conflict'] != speaker_conflict(ja['speaker'], zh['speaker']):
                raise ValueError('Ledger localization speaker difference mismatch')
            expected = plain_text(zh['raw_text'])
            if zh['strings'][0]['raw_hex'] == ja['strings'][0]['raw_hex'] and re.search('[ぁ-ヿ一-鿿]', ja['raw_text']):
                expected = None
            if row['zh_text'] != expected:
                raise ValueError('Ledger Chinese translation mismatch')
        count += 1
    for relative, offsets in supplied.items():
        if offsets != set(parsed[relative]):
            raise ValueError('Ledger source opcode coverage incomplete')
    blocks = {}
    for row in rows:
        blocks.setdefault((row['source_file'], row['segment']), []).append(row)
    for own in blocks.values():
        explicit = any(EXPLICIT.search((r['ja_raw_text'] or '') + '\n' + (r['zh_raw_text'] or '')) for r in own)
        expected = 'explicit' if explicit else 'safe_screened'
        if any(r['scene_safety'] != expected for r in own):
            raise ValueError('Ledger automatic scene screening mismatch')
    return {'status': 'passed', 'source_records_reparsed': count, 'source_files_reparsed': len(parsed),
            'human_listening_certified': False}


def voice_inventory():
    rows = []
    for source, archive_name in [('base', 'voice'), ('extended', 'voice2')]:
        ledger = OUTPUT / f'source/hotaru_voice_{source}_extraction.jsonl'
        archive = GAME / 'data/pack' / (archive_name + '.cpz')
        archive_sha = sha(archive)
        for line in ledger.read_text(encoding='utf-8-sig').splitlines():
            item = json.loads(line)
            path = OUTPUT / 'voice' / archive_name / item['name'].replace('\\', '/')
            if sha(path) != item['sha256']:
                raise ValueError('Extracted Hotaru audio hash mismatch')
            name = path.stem
            if not name.startswith('hosn') or '04_ほたる' not in item['name']:
                raise ValueError('Unexpected Hotaru speaker archive directory')
            rows.append({'voice_id': name, 'character_id': 'hotaru', 'path': path.relative_to(ROOT).as_posix(),
                         'sha256': item['sha256'], 'bytes': item['bytes'],
                         'archive_path': archive.relative_to(ROOT).as_posix(), 'archive_sha256': archive_sha,
                         'archive_entry': item['name'], 'archive_offset': item['offset'],
                         'archive_packed_bytes': item['packed_bytes'], 'audio_language': 'ja',
                         'speaker_identity_basis': 'original archive directory 04_ほたる and script hosn/speaker-index-4 agreement'})
    if len({r['voice_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate Hotaru voice IDs require explicit version handling')
    write_rows(OUTPUT / 'source/hotaru_voice_inventory.jsonl', rows)
    print(f'Original Hotaru OGG inventory verified: {len(rows)}', flush=True)
    return rows


def audit_sources():
    archives = {}
    variants = []
    definitions = [('ja_inventory.jsonl', 'ja/base', 'data/pack/script.cpz'),
                   ('ja_update_inventory.jsonl', 'ja/update', 'data/pack/update.cpz'),
                   ('zh_inventory.jsonl', None, None)]
    selected = {'ja': source_file_map('ja'), 'zh': source_file_map('zh')}
    for inventory_name, source_prefix, archive_name in definitions:
        inventory = OUTPUT / 'source' / inventory_name
        for line in inventory.read_text(encoding='utf-8-sig').splitlines():
            item = json.loads(line)
            if source_prefix:
                language = 'ja'
                path = OUTPUT / 'source' / source_prefix / item['name'].replace('\\', '/')
                archive = GAME / archive_name
                expected = item['sha256']
                entry, offset, packed = item['name'], item['offset'], item['packed_bytes']
            else:
                language = 'zh'
                path = ROOT / item['decoded_path']
                archive = ROOT / item['archive_path']
                expected = item['decoded_sha256']
                entry, offset, packed = item['archive_entry'], item['offset'], item['packed_size']
            if sha(path) != expected:
                raise ValueError('Decoded source no longer equals extraction ledger')
            archive_relative = archive.relative_to(ROOT).as_posix()
            if archive_relative not in archives:
                archives[archive_relative] = {'bytes': archive.stat().st_size, 'sha256': sha(archive)}
            variants.append({'language': language, 'source_file': path.name, 'decoded_path': path.relative_to(ROOT).as_posix(),
                             'decoded_sha256': expected, 'archive_path': archive_relative,
                             'archive_sha256': archives[archive_relative]['sha256'],
                             'archive_entry': entry, 'archive_offset': offset, 'archive_packed_bytes': packed,
                             'effective_selected': path == selected[language].get(path.name),
                             'selection_policy': 'official update over base for Japanese; Chinese Scriptspk.UPD over Pk/Scripts.pk'})
    write_json(OUTPUT / 'source/source_inventory.json', {'archives': archives, 'script_variants': variants,
               'original_data_read_only': True, 'JA_update_member_names_retained': True,
               'selection_does_not_delete_other_variants': True})
    print(f'Source archive provenance verified: {len(archives)} archives, {len(variants)} decoded script versions', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extract-zh', action='store_true')
    parser.add_argument('--align', action='store_true')
    parser.add_argument('--voice-inventory', action='store_true')
    parser.add_argument('--audit-sources', action='store_true')
    args = parser.parse_args()
    if args.extract_zh:
        inventory = []
        for name, path in [('base', GAME / 'Pk/Scripts.pk'), ('update', GAME / 'Scriptspk.UPD')]:
            own = extract_pkp(path, OUTPUT / 'source/zh' / name)
            inventory += own
            print(f'Extracted ZH {name}: {len(own)} PS3 members', flush=True)
        write_rows(OUTPUT / 'source/zh_inventory.jsonl', inventory)
    if args.align:
        align_sources()
    if args.voice_inventory:
        voice_inventory()
    if args.audit_sources:
        audit_sources()


if __name__ == '__main__':
    main()
