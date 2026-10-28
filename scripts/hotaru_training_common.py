"""Portable verification/policy for the CMVS Hotaru handoff, never training code."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
import wave

SPLITS = ('train', 'validation', 'test')
LISTS = ('all', 'train', 'validation', 'test', 'fewshot_15min')
KANA = re.compile(r'[\u3040-\u30ff\uff66-\uff9f]')
EXPLICIT = re.compile(r'性交|阴茎|阴道|乳头|射精|精液|手淫|口交|肛交|强奸|肉棒|小穴|乳房|下体|高潮|裸体|'
    r'胸部|胸罩|内裤|勃起|发情|侍寝|裙底|处女|性欲|插入|抽插|做爱|性行为|上床|'
    r'膣|中出し|フェラ|パイズリ|アナル|潮吹|絶頂|子宮|乳首|セックス|精液|ザーメン|'
    r'ちんぽ|ちんこ|まんこ|おまんこ|チンポ|マンコ|クンニ|手マン|オナニー|レイプ')
PRIVATE = re.compile(r'心想|暗想|内心|心里|心中|心底|暗自|想必|或许|大概|恐怕|回忆|记得|'
    r'觉得|认为|意识|脑海|不知|知道|明白|思考|打算|琢磨|秘密|瞒着|梦见|幻想|猜|似乎|也许')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def payload_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def json_read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def rows_read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def rows_write(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def safe_path(root, name):
    if not isinstance(name, str) or not name or ':' in name or '\\' in name:
        raise ValueError('Invalid relative path')
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or p.as_posix() != name:
        raise ValueError('Unsafe relative path')
    target = root.joinpath(*p.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path escapes package')
    if any(p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(root)):
        raise ValueError('Symlink in package path')
    return target


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if c.isalnum()).lower()


def japanese_label(text):
    """Preserve original full-width spaces; only flatten list-breaking whitespace."""
    return re.sub(r'[\r\n\t]+', ' ', text).strip()


def chinese_error(text):
    if not isinstance(text, str) or not text.strip():
        return 'empty_chinese'
    if '\ufffd' in text or any(ord(c) < 32 and c not in '\n\t' for c in text):
        return 'invalid_character'
    if KANA.search(text) or not re.search(r'[\u4e00-\u9fff]', text):
        return 'not_chinese'
    if re.search(r'\[(?:>>|<<|font|ruby)|<\||https?://', text):
        return 'markup'
    if EXPLICIT.search(text):
        return 'explicit_context'
    if len(text) > 6000:
        return 'too_long'
    return None


def target_error(text):
    error = chinese_error(text)
    if error:
        return error
    if not 3 <= len(normalized(text)) <= 400:
        return 'target_length'
    if re.fullmatch(r'[嗯啊呼哈唔呜喵哼哦呀诶唉噗咕呃嘿嘻耶\W]+', text):
        return 'nonverbal'
    return None


def context_rows(rows, index):
    target = rows[index]
    previous = []
    for row in reversed(rows[max(0, index - 6):index]):
        if (row['source_file'], row.get('scene_id'), row.get('segment')) != (target['source_file'], target.get('scene_id'), target.get('segment')):
            break
        previous.append(row)
    previous.reverse()
    return previous


def context_error(target, previous):
    error = target_error(target.get('zh_text'))
    if error:
        return error
    if target.get('alignment_status') != 'confirmed':
        return 'alignment_unconfirmed'
    if target.get('scene_safety') in ('explicit', 'intimate', 'unknown'):
        return 'scene_requires_review'
    if len(previous) < 2:
        return 'insufficient_preceding_context'
    if sum(len(r.get('zh_text') or '') for r in previous) > 1800:
        return 'context_too_long'
    if sum(len(normalized(r.get('zh_text') or '')) >= 3 for r in previous) < 2:
        return 'context_is_only_nonverbal'
    for row in previous + [target]:
        if row.get('localized_speaker_conflict'):
            return 'localized_speaker_conflict'
        if row.get('branch_uncertain') or row.get('scene_safety') in ('explicit', 'intimate', 'unknown'):
            return 'unresolved_scene_or_branch'
        if EXPLICIT.search(row.get('ja_text') or ''):
            return 'japanese_explicit_context'
        if row is not target:
            if (not row.get('speaker') and row.get('evidence_type') != 'narration') or row.get('speaker') in ('???', '？？？'):
                return 'unknown_context_speaker'
            error = chinese_error(row.get('zh_text'))
            if error and normalized(row.get('zh_text') or ''):
                return 'context_' + error
            if row.get('evidence_type') == 'narration' and PRIVATE.search(row.get('zh_text') or ''):
                return 'private_narration'
            if len(normalized(target['zh_text'])) >= 6 and normalized(target['zh_text']) in normalized(row.get('zh_text') or ''):
                return 'target_already_in_input'
    return None


def display_speaker(row):
    if row.get('evidence_type') == 'narration':
        return '旁白（仅可观察部分）'
    # Localized names are source labels, not inferred names from Japanese readings.
    name = re.sub(r'\s+', '', row.get('zh_speaker_raw') or row['speaker'])
    if KANA.search(name):
        aliases = {'ほたる': '萤', 'こころ': '心', 'あずき': '杏月', '誠': '诚'}
        name = aliases.get(name, '未确认中文姓名的人物')
    return name


def prompt(target, previous):
    player = previous[-1].get('character') == 'makoto' or previous[-1]['speaker'] in ('誠', '诚', '織部誠', '织部诚')
    others = {r['speaker'] for r in previous if r.get('evidence_type') != 'narration'} - {'誠', '诚', '織部誠', '织部诚', target['speaker']}
    direct = player and (not others or '萤' in previous[-1]['zh_text'])
    history = previous[:-1] if direct else previous
    lines = ['【任务】依据以下原作片段，输出水无月萤此刻说出的一句中文台词。',
             '【身份模式】protagonist：当前是《天津罪》原作场景续演，诚是原作主角；不是现实用户的共同记忆。']
    lines += ['【此前剧情】' + display_speaker(r) + '：' + r['zh_text'] for r in history]
    lines.append('【当前玩家台词】诚：' + previous[-1]['zh_text'] if direct else '【当前场景】轮到水无月萤发言；不推定上一句一定指向玩家。')
    return '\n'.join(lines), 'player_interaction' if direct else 'scene_continuation'


def manifest_write(root):
    json_write(root / 'manifest.json', {'algorithm': 'SHA256', 'files': {
        p.relative_to(root).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
        for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}})


def verify_manifest(root):
    manifest = json_read(root / 'manifest.json')['files']
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p != root / 'manifest.json'}
    if actual != set(manifest):
        raise ValueError('Manifest coverage mismatch')
    for name, meta in manifest.items():
        p = safe_path(root, name)
        if not p.is_file() or p.stat().st_size != meta['bytes'] or sha(p) != meta['sha256']:
            raise ValueError('File checksum mismatch: ' + name)
    return len(manifest)


def verify_sources(root, rows):
    spec = importlib.util.spec_from_file_location('hotaru_pack_source_reader', root / 'tools/source_reader.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_ledger(root, rows)


def verify_text(root, ledger, package):
    canonical = rows_read(root / 'provenance/canonical.jsonl')
    excluded = rows_read(root / 'provenance/excluded.jsonl')
    ids, groups, targets, normalized_replies = set(), {}, set(), set()
    ordered = list(ledger.values())
    positions = {r['id']: i for i, r in enumerate(ordered)}
    partition = json_read(root / 'source/partition.json')
    for row in canonical:
        target = ledger[row['target_id']]
        if row['sample_id'] in ids or row['target_id'] in targets or target['character'] != 'hotaru':
            raise ValueError('Repeated or wrong-character canonical sample')
        ids.add(row['sample_id'])
        targets.add(row['target_id'])
        previous = context_rows(ordered, positions[target['id']])
        if row['context_ids'] != [r['id'] for r in previous] or context_error(target, previous):
            raise ValueError('Unsafe or leaked canonical context')
        expected_prompt, kind = prompt(target, previous)
        sample = row['sample']
        if sample != {'system': (root / 'system.txt').read_text(encoding='utf-8'), 'conversations': [
            {'from': 'human', 'value': expected_prompt}, {'from': 'gpt', 'value': target['zh_text']}]}:
            raise ValueError('Canonical sample differs from exact source context')
        if row['payload_sha256'] != payload_sha(sample) or row['sample_kind'] != kind:
            raise ValueError('Canonical content hash/type mismatch')
        split = row['split']
        if split not in SPLITS or row['group_id'] != target['source_file']:
            raise ValueError('Invalid split/group')
        if split != partition[target['source_file']]:
            raise ValueError('Canonical split differs from source-file partition')
        if groups.setdefault(row['group_id'], split) != split:
            raise ValueError('Source file leaked across partitions')
        key = normalized(target['zh_text'])
        if key in normalized_replies:
            raise ValueError('Duplicate canonical target')
        normalized_replies.add(key)
    all_hotaru = {r['id'] for r in ordered if r.get('character') == 'hotaru'}
    if targets & {r['target_id'] for r in excluded} or targets | {r['target_id'] for r in excluded} != all_hotaru:
        raise ValueError('Canonical/exclusion accounting incomplete')
    synthetic = rows_read(root / 'synthetic/candidates.jsonl')
    for row in synthetic:
        if row['sample_id'] in ids or row['source_type'] != 'synthetic' or row['review_status'] != 'candidate_pending_human':
            raise ValueError('Invalid or falsely approved synthetic candidate')
        if row['payload_sha256'] != payload_sha(row['sample']) or not row['not_original_game_quote']:
            raise ValueError('Invalid synthetic provenance')
        ids.add(row['sample_id'])
    for variant in ('canonical_context_only', 'mixed_sft_v3'):
        for split in SPLITS:
            expected = [r['sample'] for r in canonical if r['split'] == split]
            if json_read(root / f'sft/{variant}/{split}.json') != expected:
                raise ValueError('Formal SFT differs or contains unapproved synthetic data')
    return {'canonical': len(canonical), 'excluded': len(excluded), 'synthetic_pending': len(synthetic),
            'splits': dict(Counter(r['split'] for r in canonical)), 'source_groups': len(groups)}


def verify_tts(root, ledger, package):
    index = rows_read(root / 'alignment/index.jsonl')
    accepted = rows_read(root / 'tts_adaptation/hotaru/accepted.jsonl')
    excluded = rows_read(root / 'tts_adaptation/hotaru/excluded.jsonl')
    by_id = {r['utterance_id']: r for r in index}
    if len(by_id) != len(index) or set(by_id) != {r['utterance_id'] for r in accepted + excluded} or len(accepted) + len(excluded) != len(index):
        raise ValueError('Audio acceptance/exclusion accounting incomplete')
    native = rows_read(root / 'source/hotaru_voice_inventory.jsonl')
    native_by_voice = {r['voice_id']: r for r in native}
    if len(native_by_voice) != len(native) or {r['voice_id'] for r in index} != set(native_by_voice):
        raise ValueError('Native audio inventory coverage mismatch')
    for row in index:
        if row['original_audio_sha256'] != native_by_voice[row['voice_id']]['sha256']:
            raise ValueError('Original audio provenance hash changed')
    partition = json_read(root / 'source/partition.json')
    audio_paths, pcm_hashes, groups = set(), set(), {}
    for row in accepted:
        if row != by_id[row['utterance_id']] or row['character_id'] != 'hotaru' or row['audio_language'] != 'ja':
            raise ValueError('Wrong speaker/language/audio row')
        sources = [ledger[i] for i in row['source_line_ids']]
        if not sources or any(s['character'] != 'hotaru' or s['voice_id'] != row['voice_id'] or japanese_label(s['ja_text']) != row['ja_text'] for s in sources):
            raise ValueError('Japanese transcript/audio source mismatch')
        if any(s['alignment_status'] != 'confirmed' for s in sources):
            raise ValueError('Unconfirmed source used as training label')
        path = safe_path(root, row['audio_path'])
        pcm_hash = hashlib.sha256()
        with wave.open(str(path), 'rb') as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getcomptype()) != (32000, 1, 2, 'NONE'):
                raise ValueError('Wrong PCM WAV format')
            frames, actual = audio.getnframes(), 0
            while True:
                raw = audio.readframes(65536)
                if not raw:
                    break
                actual += len(raw)
                pcm_hash.update(raw)
            if actual != frames * 2 or abs(frames / 32000 - row['duration_seconds']) > 1 / 32000:
                raise ValueError('Truncated WAV/duration mismatch')
        value = pcm_hash.hexdigest()
        if value != row['pcm_sha256'] or value in pcm_hashes or row['audio_path'] in audio_paths:
            raise ValueError('Duplicate or changed PCM audio')
        pcm_hashes.add(value)
        audio_paths.add(row['audio_path'])
        for source in sources:
            if row['group_split'] != partition[source['source_file']]:
                raise ValueError('Audio differs from global source-file partition')
            if groups.setdefault(source['source_file'], row['group_split']) != row['group_split']:
                raise ValueError('Audio source group leaked across splits')
    refs = json_read(root / 'references/hotaru.json')
    ref_ids = {r['utterance_id'] for r in refs}
    for ref in refs:
        if ref['utterance_id'] not in by_id or by_id[ref['utterance_id']]['split'] != 'reference' or ref['ja_text'] != by_id[ref['utterance_id']]['ja_text']:
            raise ValueError('Invalid reference transcript/reservation')
    fewshot = json_read(root / 'tts_adaptation/hotaru/fewshot_ids.json')
    if len(fewshot) != len(set(fewshot)) or set(fewshot) & ref_ids or sum(by_id[i]['duration_seconds'] for i in fewshot) > 900.0001:
        raise ValueError('Invalid fewshot subset')
    if any(by_id[i]['split'] != 'train' for i in fewshot):
        raise ValueError('Fewshot must be train-only')
    for name in LISTS:
        own = accepted if name == 'all' else [r for r in accepted if r['utterance_id'] in fewshot] if name == 'fewshot_15min' else [r for r in accepted if r['split'] == name]
        expected = [f"{r['audio_path']}|hotaru|ja|{r['ja_text']}" for r in own]
        if (root / f'tts_adaptation/hotaru/labels/{name}.list').read_text(encoding='utf-8').splitlines() != expected:
            raise ValueError('Invalid Japanese .list labels/coverage')
    actual_wavs = {p.relative_to(root).as_posix() for p in root.rglob('*.wav')}
    if actual_wavs != audio_paths:
        raise ValueError('Unindexed WAV in package')
    cross = rows_read(root / 'crosslingual_alignment/hotaru.jsonl')
    expected_cross = [r for r in index if r['ja_text'] and r['zh_variants'] and r['alignment_status'] == 'confirmed']
    if cross != expected_cross:
        raise ValueError('Crosslingual alignment coverage mismatch')
    for row in cross:
        if row != by_id[row['utterance_id']]:
            raise ValueError('Crosslingual index changed')
        sources = [ledger[i] for i in row['source_line_ids']]
        if not sources or any(s['character'] != 'hotaru' or s['voice_id'] != row['voice_id'] or japanese_label(s['ja_text']) != row['ja_text'] or s['alignment_status'] != 'confirmed' for s in sources):
            raise ValueError('Crosslingual source identity/transcript not confirmed')
        for variant in row['zh_variants']:
            if any(ledger[i]['zh_text'] != variant['zh_text'] for i in variant['source_line_ids']):
                raise ValueError('Chinese translation/source variant mismatch')
        expected_variants = {}
        for ident in row['source_line_ids']:
            text = ledger[ident].get('zh_text')
            if text:
                expected_variants.setdefault(text, []).append(ident)
        actual_variants = {v['zh_text']: v['source_line_ids'] for v in row['zh_variants']}
        if expected_variants != actual_variants:
            raise ValueError('Chinese translation variants were collapsed')
    targets = rows_read(root / 'zh_target_text/hotaru.jsonl')
    target_excluded = rows_read(root / 'zh_target_text/excluded.jsonl')
    wanted_ids = {r['id'] for r in ledger.values() if r.get('character') == 'hotaru'}
    all_targets = targets + target_excluded
    if len({r['source_line_id'] for r in all_targets}) != len(all_targets) or {r['source_line_id'] for r in all_targets} != wanted_ids:
        raise ValueError('Chinese target/exclusion coverage mismatch')
    for row in all_targets:
        original = ledger[row['source_line_id']]
        if row['character_id'] != 'hotaru' or row['zh_text'] != original.get('zh_text') or row['source_game_file'] != original['source_file']:
            raise ValueError('Chinese target lost its actual localization source')
    status = json_read(root / 'zh_supervised_data_status.json')
    if status['actual_chinese_recordings'] != 0 or status['valid_zh_audio_text_pairs'] != 0:
        raise ValueError('Japanese recording falsely labelled Chinese')
    return {'raw_audio': len(index), 'accepted': len(accepted), 'excluded': len(excluded),
            'accepted_hours': round(sum(r['duration_seconds'] for r in accepted) / 3600, 6),
            'splits': dict(Counter(r['split'] for r in accepted)), 'references': len(refs),
            'fewshot_seconds': round(sum(by_id[i]['duration_seconds'] for i in fewshot), 6)}


def verify(root):
    root = Path(root).resolve()
    files = verify_manifest(root)
    package = json_read(root / 'package.json')
    if package['character'] != 'hotaru' or package['models_trained'] or package['inference_run']:
        raise ValueError('Invalid package character/scope')
    rows = rows_read(root / 'source/records.jsonl')
    ledger = {r['id']: r for r in rows}
    if len(ledger) != len(rows):
        raise ValueError('Repeated source IDs')
    evidence = verify_sources(root, rows)
    versions = root / 'source/script_versions.json'
    if versions.exists():
        for item in json_read(versions):
            if sha(safe_path(root, item['package_path'])) != item['decoded_sha256']:
                raise ValueError('Original script version attachment changed')
    result = verify_text(root, ledger, package) if package['kind'] == 'text' else verify_tts(root, ledger, package)
    return {'status': 'passed', 'manifest_files': files, 'source_records': len(rows),
            'source_validation': evidence, 'data': result,
            'manual_listening_certified': False, 'models_trained': False, 'inference_run': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('verify', 'paths'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    result = verify(root)
    if args.command == 'paths':
        if json_read(root / 'package.json')['kind'] != 'tts':
            raise ValueError('paths applies only to the voice package')
        destination = (args.output_dir or root.parent / (root.name + '_absolute_paths')).resolve()
        if destination.is_relative_to(root):
            raise ValueError('Output must be outside immutable package')
        destination.mkdir(parents=True, exist_ok=True)
        for name in LISTS:
            lines = (root / f'tts_adaptation/hotaru/labels/{name}.list').read_text(encoding='utf-8').splitlines()
            converted = ['|'.join([safe_path(root, parts[0]).as_posix(), *parts[1:]]) for parts in [line.split('|') for line in lines]]
            (destination / (name + '.list')).write_text(''.join(s + '\n' for s in converted), encoding='utf-8')
        result['absolute_lists'] = str(destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
