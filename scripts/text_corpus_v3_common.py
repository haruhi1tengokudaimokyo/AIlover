"""Portable, offline V3 corpus policy and independent package verification."""
import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata

SPLITS = ('train', 'validation', 'test')
NAMES = {'hika': '绯华', 'ayame': '菖蒲', 'mugi': '麦'}
KANA = re.compile(r'[\u3040-\u30ff\uff66-\uff9f]')
EXPLICIT = re.compile(r'性交|阴茎|阴道|乳头|射精|精液|手淫|口交|肛交|强奸|肉棒|小穴|乳房|下体|高潮|裸体'
    r'|张开.{0,5}腿|身体相通|大人才会.{0,8}事|做.{0,5}大人.{0,8}事|脱.{0,8}(?:衣服|内裤)'
    r'|胸部|胸罩|内裤|勃起|发情|床上|侍寝|裙底|接吻|亲嘴|处女|性欲|肉体|插入|抽插|硬起来|身体.{0,5}结合'
    r'|色色|打出来|搞黄|色情|性经验|做爱|做过爱|发生关系|色色的|性行为|上床|色狼|色鬼|抱过我|随心所欲.{0,5}抱|羞辱')
PRIVATE_NARRATION = re.compile(r'心想|暗想|内心|心里|心中|心底|暗自|想必|或许|大概|恐怕|回忆|记得|看来|'
                              r'觉得|认为|意识|脑海|不知|知道|明白|想|思考|打算|琢磨|秘密|瞒着|梦见|幻想|猜|'
                              r'好奇|感兴趣|似乎|显然|果然|果不其然|也许|肯定|一定|早已|生气|难过|害羞|嫉妒|心动|情绪')
# Conservative scene fences. Visual character poses and sound effects are not narrative jumps.
FENCE = re.compile(r'^@(?:bgset(?:_withoutblack|_interval)?|bg_image|eyecatch|SC_StartProcess|SC_SceneStartProcess|'
                   r'SC_SceneEnd|SC_EndProcess|SL_StartSelect|SL_Join|call|return|jump|if|else|elsif|endif|h\d+)\b', re.I)
SPEAKER_ALIASES = {'緋華': '绯华', 'むぎ': '麦', '小麦': '麦', '地': '旁白（仅可观察部分）'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def payload_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def json_read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def jsonl_read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def jsonl_write(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def safe_path(root, relative):
    p = PurePosixPath(relative)
    if not relative or p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative:
        raise ValueError('Unsafe relative path: ' + relative)
    result = (Path(root) / Path(*p.parts)).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise ValueError('Path escapes package')
    return result


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if c.isalnum()).lower()


def basic_text_error(text):
    if not isinstance(text, str) or not text.strip():
        return 'empty_or_nonstring'
    if '\ufffd' in text or any(ord(c) < 32 and c not in '\n\t' for c in text):
        return 'invalid_character'
    if KANA.search(text) or not re.search(r'[\u4e00-\u9fff]', text):
        return 'not_chinese'
    if re.search(r'\[(?:>>|<<|font|ruby)|<\||https?://', text):
        return 'engine_or_prompt_markup'
    if len(text) > 6000:
        return 'too_long'
    return None


def target_error(text):
    issue = basic_text_error(text)
    if issue:
        return issue
    if not 3 <= len(normalized(text)) <= 400:
        return 'too_short_or_long'
    if EXPLICIT.search(text):
        return 'intimate_or_explicit_context'
    if normalized(text) in ('去死吧', '去死', '滚开', '闭嘴', '滚'):
        return 'hostile_short_reply'
    if re.fullmatch(r'[嗯啊呼哈唔呜喵哼哦呀诶唉噗咕呃嘿嘻耶\W]+', text):
        return 'nonverbal_or_breath'
    return None


def context_error(row):
    text = row['text']
    if not isinstance(row.get('speaker'), str) or row['speaker'] in ('', '？？？', '???'):
        return 'unknown_speaker'
    # Ellipses are genuine turns, not silently discarded; they cannot be the whole window.
    if normalized(text) and basic_text_error(text):
        return basic_text_error(text)
    if '\ufffd' in text or '[' in text or ']' in text or KANA.search(text):
        return 'context_markup_or_language'
    if EXPLICIT.search(text):
        return 'intimate_or_explicit_context'
    if row['evidence_type'] == 'narration' and PRIVATE_NARRATION.search(text):
        return 'private_narration_or_inferred_knowledge'
    return None


def attach_scenes(rows, text):
    """Retain original IDs while adding stricter physical-line scene boundaries."""
    lines = text.splitlines()
    fences = []
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('*') or FENCE.search(stripped):
            fences.append(number)
    for row in rows:
        start = row['source_location']['line_start']
        fence = max((n for n in fences if n < start), default=0)
        row['v3_scene'] = f"{row['source_file']}@{fence}:segment{row['segment']}"
    return rows


def context_window(rows, index, maximum=6):
    target = rows[index]
    if target.get('branch'):
        return [], 'conditional_branch_unresolved'
    prior = []
    for row in reversed(rows[max(0, index - maximum):index]):
        if row['source_file'] != target['source_file'] or row['v3_scene'] != target['v3_scene']:
            break
        if row.get('branch'):
            return [], 'conditional_branch_unresolved'
        prior.append(row)
    prior.reverse()
    if len(prior) < 2:
        return prior, 'insufficient_preceding_context'
    for row in prior:
        error = context_error(row)
        if error:
            return prior, error
    if sum(len(normalized(r['text'])) >= 3 for r in prior) < 2:
        return prior, 'context_is_only_nonverbal'
    target_norm = normalized(target['text'])
    if len(target_norm) >= 6 and any(target_norm in normalized(r['text']) for r in prior):
        return prior, 'target_already_in_input'
    if sum(len(r['text']) for r in prior) > 1800:
        return prior, 'context_too_long'
    return prior, None


def interaction_kind(target, prior):
    """Adjacency alone is insufficient: require two-person continuity or explicit address."""
    current = prior[-1]
    if current['speaker'] != '肇' or current['evidence_type'] != 'dialogue':
        return 'scene_continuation'
    others = {r['speaker'] for r in prior if r['evidence_type'] == 'dialogue'} - {'肇', target['speaker']}
    name = NAMES[target['character']]
    explicit_address = name in current['text'] and not any(s in current['text'] for s in others)
    if others and not explicit_address:
        return 'scene_continuation'
    return 'player_interaction'


def context_prompt(target, prior, kind):
    current = prior[-1] if kind == 'player_interaction' else None
    history = prior[:-1] if current else prior
    lines = ['【任务】依据以下原作片段，输出' + NAMES[target['character']] + '此刻说出的一句中文台词。',
             '【身份模式】protagonist：当前是原作场景续演，肇是原作主角；不是现实用户的共同记忆。']
    for row in history:
        speaker = SPEAKER_ALIASES.get(row['speaker'], row['speaker'])
        lines.append('【此前剧情】' + speaker + '：' + row['text'])
    if current:
        lines.append('【当前玩家台词】肇：' + current['text'])
    else:
        lines.append('【当前场景】轮到' + NAMES[target['character']] + '发言；不假定上一句是在向玩家提问。')
    return '\n'.join(lines)


def near_pairs(records, minimum=12, threshold=.9):
    """Exact/near reply detector; length/trigram blocking avoids quadratic comparisons."""
    buckets = defaultdict(set)
    norms, pairs = [], []
    for i, row in enumerate(records):
        text = normalized(row['sample']['conversations'][-1]['value'])
        grams = {text[j:j + 3] for j in range(len(text) - 2)}
        candidates = set()
        if len(text) >= minimum:
            for gram in grams:
                candidates.update(buckets[gram])
        for j in sorted(candidates):
            old = norms[j]
            if abs(len(old) - len(text)) > max(len(text), len(old)) * (1 - threshold) * 2:
                continue
            ratio = SequenceMatcher(None, old, text, autojunk=False).ratio()
            if ratio >= threshold:
                pairs.append({'left': records[j]['sample_id'], 'right': row['sample_id'],
                              'ratio': round(ratio, 5), 'exact': old == text})
        norms.append(text)
        if len(text) >= minimum:
            for gram in grams:
                buckets[gram].add(i)
    return pairs


def sharegpt_error(sample):
    if not isinstance(sample, dict) or basic_text_error(sample.get('system')):
        return 'invalid_system'
    messages = sample.get('conversations')
    if not isinstance(messages, list) or len(messages) < 2 or len(messages) % 2:
        return 'invalid_turn_count'
    for i, message in enumerate(messages):
        if not isinstance(message, dict) or message.get('from') != ('human' if i % 2 == 0 else 'gpt'):
            return 'invalid_role_alternation'
        if basic_text_error(message.get('value')):
            return 'invalid_message_text'
    return None


def manifest_write(folder):
    files = {p.relative_to(folder).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
             for p in sorted(folder.rglob('*')) if p.is_file() and p != folder / 'manifest.json' and '__pycache__' not in p.parts}
    json_write(folder / 'manifest.json', {'algorithm': 'SHA256', 'files': files})


def load_parser(root):
    spec = importlib.util.spec_from_file_location('v3_package_story_parser', root / 'tools/story_parser.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_package(root):
    root = Path(root)
    manifest = json_read(root / 'manifest.json')['files']
    for name, item in manifest.items():
        path = safe_path(root, name)
        if not path.is_file() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError('Checksum mismatch: ' + name)
        if path.suffix == '.json':
            json_read(path)
        elif path.suffix == '.jsonl':
            jsonl_read(path)
    for path in root.rglob('*'):
        if path.is_file() and path != root / 'manifest.json' and '__pycache__' not in path.parts:
            if path.relative_to(root).as_posix() not in manifest:
                raise ValueError('Unmanifested input file')
    package = json_read(root / 'package.json')
    slug = package['character']
    baseline = root / 'baseline_reference'
    original_manifest = json_read(baseline / 'manifest.json')['files']
    for name, item in original_manifest.items():
        path = safe_path(baseline, name)
        if path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError('Read-only V2 baseline copy changed')
    parser = load_parser(root)
    ledger = {r['id']: r for r in jsonl_read(root / 'source/records.jsonl')}
    parsed = {}
    for item in json_read(root / 'source/inventory.json')['scripts']:
        for language in ('zh', 'ja'):
            path = safe_path(root, item[language + '_path'])
            if sha(path) != item[language + '_sha256']:
                raise ValueError('Source script hash mismatch')
            rows, _ = parser.parse_script(path, root / 'source' / language)
            if language == 'zh':
                attach_scenes(rows, parser.decode_source(path)[0])
                parsed.update({r['id']: r for r in rows})
            else:
                for row in rows:
                    if row['id'] in ledger and ledger[row['id']]['jp_script_sha256'] != row['source_sha256']:
                        raise ValueError('Japanese source hash mismatch')
    for ident, row in ledger.items():
        actual = parsed[ident]
        for key in ('text', 'speaker', 'character', 'source_file', 'source_location', 'source_sha256', 'sequence', 'v3_scene', 'segment'):
            if row[key] != actual[key]:
                raise ValueError('Source ledger differs from actual KS: ' + ident + ':' + key)
    records = jsonl_read(root / 'provenance/canonical.jsonl')
    synthetic = jsonl_read(root / 'synthetic/candidates.jsonl')
    all_by_id = {r['sample_id']: r for r in records + synthetic}
    if len(all_by_id) != len(records) + len(synthetic):
        raise ValueError('Duplicate sample IDs')
    source_groups, targets = defaultdict(set), defaultdict(set)
    partition = json_read(root / 'source/partition.json')['assignment']
    for row in records:
        target = ledger[row['target_id']]
        prior = [ledger[ident] for ident in row['context_ids']]
        if (target['character'] != slug or target['speaker'] != NAMES[slug] or row['character'] != slug
                or row['source_type'] != 'canonical'):
            raise ValueError('Wrong target speaker/character')
        if not 2 <= len(prior) <= 6 or len({r['id'] for r in prior}) != len(prior):
            raise ValueError('Invalid context window')
        if any(r['source_file'] != target['source_file'] or r['v3_scene'] != target['v3_scene']
               or r['source_location']['line_end'] >= target['source_location']['line_start']
               or r['sequence'] >= target['sequence'] for r in prior):
            raise ValueError('Future, route, or scene leakage')
        if [r['sequence'] for r in prior] != list(range(target['sequence'] - len(prior), target['sequence'])):
            raise ValueError('Dropped intervening dialogue')
        if target_error(target['text']) or any(context_error(r) for r in prior) or target.get('branch'):
            raise ValueError('Failed source quality policy')
        if sharegpt_error(row['sample']) or row['sample']['conversations'][-1]['value'] != target['text']:
            raise ValueError('Changed original reply or invalid ShareGPT')
        if row['sample']['conversations'][0]['value'] != context_prompt(target, prior, row['sample_kind']):
            raise ValueError('Input is not reconstructed from preceding source')
        if row['sample_kind'] != interaction_kind(target, prior):
            raise ValueError('Wrong direct-reply classification')
        if row['group_id'] != target['source_file']:
            raise ValueError('Scene derivatives do not share a file group')
        if row['split'] != partition[row['group_id']]:
            raise ValueError('Sample differs from global file partition')
        if row['payload_sha256'] != payload_sha(row['sample']):
            raise ValueError('Sample content hash mismatch')
        source_groups[row['split']].add(row['group_id'])
        targets[row['split']].add(normalized(target['text']))
    for i, left in enumerate(SPLITS):
        for right in SPLITS[i + 1:]:
            if source_groups[left] & source_groups[right] or targets[left] & targets[right]:
                raise ValueError('Train/validation/test source or answer overlap')
    for row in synthetic:
        required = ('source_type', 'character', 'scenario_type', 'generation_model', 'review_status', 'canon_fact_refs', 'sample_id', 'group_id', 'split')
        if any(key not in row for key in required) or row['source_type'] != 'synthetic' or row['character'] != slug:
            raise ValueError('Unlabelled synthetic content')
        if sharegpt_error(row['sample']) or row['payload_sha256'] != payload_sha(row['sample']):
            raise ValueError('Invalid synthetic conversation')
        if any(ident not in ledger for ident in row['canon_fact_refs']):
            raise ValueError('Unknown synthetic canon evidence')
        if any(ledger[ident]['source_file'] not in source_groups['train'] for ident in row['canon_fact_refs']):
            raise ValueError('Synthetic construction used held-out original material')
    templates = defaultdict(set)
    for row in synthetic:
        templates[row['split']].add(row['group_id'])
    if any(templates[a] & templates[b] for i, a in enumerate(SPLITS) for b in SPLITS[i + 1:]):
        raise ValueError('Synthetic seed/template leakage')
    counts = {}
    registrations = json_read(root / 'sft/dataset_info.json')
    for name, config in registrations.items():
        if config.get('formatting') != 'sharegpt' or config['columns'] != {'messages': 'conversations', 'system': 'system'}:
            raise ValueError('Incorrect LLaMA-Factory registration')
        samples = json_read(safe_path(root / 'sft', config['file_name']))
        if not isinstance(samples, list) or not samples or any(sharegpt_error(s) for s in samples):
            raise ValueError('Empty/malformed registered SFT dataset')
        counts[name] = len(samples)
    for variant in ('canonical_context_only', 'mixed_sft_v3'):
        for split in SPLITS:
            ids = json_read(root / f'sft/{variant}/{split}_ids.json')
            samples = json_read(root / f'sft/{variant}/{split}.json')
            if len(ids) != len(set(ids)) or samples != [all_by_id[ident]['sample'] for ident in ids]:
                raise ValueError('SFT/provenance mismatch')
            for ident in ids:
                row = all_by_id[ident]
                if row['split'] != split:
                    raise ValueError('Incorrect partition export')
                if row['source_type'] == 'synthetic' and (variant == 'canonical_context_only' or row['review_status'] != 'human_approved'):
                    raise ValueError('Unapproved synthetic data entered training')
            synthetic_count = sum(all_by_id[i]['source_type'] == 'synthetic' for i in ids)
            if variant == 'mixed_sft_v3' and split == 'train' and synthetic_count / max(len(ids), 1) > .25:
                raise ValueError('Synthetic training share exceeds cap')
    cross = []
    for pair in near_pairs(records):
        if all_by_id[pair['left']]['split'] != all_by_id[pair['right']]['split']:
            cross.append(pair)
    if cross:
        raise ValueError('Near duplicate responses across partitions')
    synthetic_pairs = near_pairs(synthetic)
    if any(all_by_id[p['left']]['split'] != all_by_id[p['right']]['split'] for p in synthetic_pairs):
        raise ValueError('Near duplicate synthetic replies across candidate partitions')
    exact_synthetic = defaultdict(set)
    for row in synthetic:
        exact_synthetic[normalized(row['sample']['conversations'][-1]['value'])].add(row['split'])
    if any(len(splits) > 1 for splits in exact_synthetic.values()):
        raise ValueError('Exact synthetic response appears in multiple partitions')
    official = records + [r for r in synthetic if r['review_status'] == 'human_approved']
    official_exact = defaultdict(set)
    for row in official:
        official_exact[normalized(row['sample']['conversations'][-1]['value'])].add(row['split'])
    if any(len(splits) > 1 for splits in official_exact.values()):
        raise ValueError('Canonical/synthetic answer leakage across partitions')
    if any(all_by_id[p['left']]['split'] != all_by_id[p['right']]['split'] for p in near_pairs(official)):
        raise ValueError('Near canonical/synthetic answer leakage across partitions')
    for split in ('validation', 'test'):
        for heldout in (r for r in records if r['split'] == split):
            answer = normalized(heldout['sample']['conversations'][-1]['value'])
            if len(answer) >= 12 and any(answer in normalized(r['sample']['conversations'][0]['value'])
                   for r in records if r['split'] == 'train'):
                raise ValueError('Held-out target copied into training context')
    evaluation = jsonl_read(root / 'evaluation/heldout_cases.jsonl')
    if len({r['case_id'] for r in evaluation}) != len(evaluation):
        raise ValueError('Duplicate evaluation IDs')
    for case in evaluation:
        messages = case['messages']
        if not messages or len(messages) % 2 != 1 or any(m['from'] != ('human' if i % 2 == 0 else 'gpt')
                 or basic_text_error(m['value']) for i, m in enumerate(messages)):
            raise ValueError('Malformed held-out chat history')
    training_inputs = {normalized(m['value']) for r in records + synthetic for m in r['sample']['conversations'] if m['from'] == 'human'}
    if any(normalized(r['messages'][-1]['value']) in training_inputs for r in evaluation):
        raise ValueError('Evaluation question copied into train/generation inputs')
    return {'status': 'passed', 'character': slug, 'canonical_samples': len(records),
            'synthetic_candidates': len(synthetic), 'counts': counts, 'verified_files': len(manifest),
            'future_leakage': 0, 'cross_partition_near_duplicates': 0,
            'semantic_translation_correctness': 'requires_human_review', 'model_quality': 'not_tested'}


def score_predictions(root, prediction_path):
    """Offline diagnostics only; rubric scores require a real reviewer."""
    expected = {r['case_id']: r for r in jsonl_read(root / 'evaluation/heldout_cases.jsonl')}
    actual = jsonl_read(prediction_path)
    if len({r['case_id'] for r in actual}) != len(actual) or any(r['case_id'] not in expected for r in actual):
        raise ValueError('Duplicate/unknown evaluation case ID')
    return {'evaluated': len(actual), 'missing': len(expected) - len(actual),
            'empty_answers': sum(not isinstance(r.get('answer'), str) or not r['answer'].strip() for r in actual),
            'kana_answers': sum(bool(KANA.search(r.get('answer') or '')) for r in actual),
            'rubric_scores': 'not_automatically_inferred', 'role_fidelity': 'requires_blind_human_review'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('verify', 'score'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--predictions', type=Path)
    args = parser.parse_args()
    if args.command == 'score' and not args.predictions:
        parser.error('--predictions is required')
    result = verify_package(args.root) if args.command == 'verify' else score_predictions(args.root, args.predictions)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
