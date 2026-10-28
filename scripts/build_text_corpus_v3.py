"""Rebuild three private text-only corpora without editing V2/game/app/voice files.

Python 3.10+, standard library. No remote model calls and no model training.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import importlib.util
import io
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

from text_corpus_v3_common import (NAMES, SPLITS, attach_scenes, basic_text_error, context_window,
    context_prompt, interaction_kind, json_read, json_write, jsonl_read, jsonl_write, manifest_write,
    near_pairs, normalized, payload_sha, safe_path, sha, sharegpt_error, target_error, verify_package)
from text_v3_editorial import EDITORIAL, FACT_CANDIDATES, evaluation_cases

ROOT = Path(__file__).resolve().parents[1]
DISPLAY = {'hika': 'Hika', 'ayame': 'Ayame', 'mugi': 'Mugi'}
RESEARCH = [
    {'name': 'ChatHaruhi', 'url': 'https://github.com/LC1332/Chat-Haruhi-Suzumiya',
     'method': '保留带人物标签的真实前序剧情；区分原作与另写互动，不强制所有台词成为问答。'},
    {'name': 'RoleLLM', 'url': 'https://github.com/InteractiveNLP-Team/RoleLLM-public',
     'method': '档案、知识证据、口吻示例分别记录；角色条件数据与评测分离。'},
    {'name': 'Character-LLM', 'url': 'https://aclanthology.org/2023.emnlp-main.814/',
     'method': '以经历和场景理解行为；不凭空给角色补内心或未经证实的情绪状态。'},
    {'name': 'CoSER', 'url': 'https://github.com/Neph0s/CoSER',
     'method': '评测具体情境下的角色表现；本包只提供离线规则和听评式人工评分表，不声称复现上游指标。'},
    {'name': 'LLaMA-Factory', 'url': 'https://llamafactory.readthedocs.io/en/latest/getting_started/data_preparation.html',
     'method': 'ShareGPT conversations 按 human/gpt 交替，system 单列，独立登记训练与验证。'},
    {'name': 'LLaMA-Factory mask_history', 'url': 'https://llamafactory.readthedocs.io/en/latest/advanced/arguments.html',
     'method': '多轮合成样本各 gpt 回答均为目标角色；建议 train_on_prompt=false，mask_history=true 以只监督当前回复。'},
]


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_v2(directory):
    found = {}
    for archive in sorted(directory.glob('*.zip'), reverse=True):
        if 'v2' not in archive.name:
            continue
        with ZipFile(archive) as z:
            members = z.namelist()
            candidates = [n for n in members if n.endswith('/package.json')]
            if len(candidates) != 1:
                continue
            prefix = candidates[0][:-len('package.json')]
            package = json.loads(z.read(candidates[0]))
            if package.get('kind') != 'text' or package.get('version') != 2:
                continue
            slug = package.get('slug')
            if slug not in NAMES or slug in found:
                continue
            if z.testzip():
                raise ValueError('V2 ZIP CRC failure')
            for name in members:
                relative = name[len(prefix):]
                safe_path(Path('.'), relative)
            manifest = json.loads(z.read(prefix + 'manifest.json'))['files']
            if set(members) != {prefix + name for name in manifest} | {prefix + 'manifest.json'}:
                raise ValueError('V2 manifest coverage mismatch')
            for name, item in manifest.items():
                raw = z.read(prefix + name)
                import hashlib
                if len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
                    raise ValueError('V2 member checksum mismatch')
            read = lambda name: json.loads(z.read(prefix + name))
            rows = lambda name: [json.loads(line) for line in z.read(prefix + name).decode('utf-8').splitlines() if line.strip()]
            found[slug] = {'path': archive, 'sha256': sha(archive), 'prefix': prefix,
                'package': package, 'train': read('sft/train.json'), 'validation': read('sft/validation.json'),
                'seeds': read('sft/seed_samples.json'), 'system': z.read(prefix + 'system.txt').decode('utf-8'),
                'references': rows('reference_only/aligned_localization.jsonl'), 'qa': read('qa.json'),
                'provenance': rows('provenance/train.jsonl') + rows('provenance/validation.jsonl'),
                'verified_member_count': len(manifest)}
    if set(found) != set(NAMES):
        raise ValueError('Could not locate all three actual V2 Chinese text packages; use --v2-dir')
    return found


def profile_v3(card):
    """Keep imported canon in a labelled section, replace ambiguous real-user equations."""
    text = card['profile']
    before = text.split('【示例对话', 1)[0].split('【边界】', 1)[0]
    before = before.replace('王様恋愛', '国王恋爱').replace('緋華', '绯华').replace('むぎ', '麦')
    before = before.replace('藤ヶ丘菖蒲', '藤丘菖蒲')
    before = re.sub(r'（原名麦，也被称作小麦）', '（也称小麦）', before)
    before = re.sub(r'([\u4e00-\u9fff]+)（\1）', r'\1', before)
    identity, _, rest = before.partition('【性格')
    identity = identity.replace('用户', '原作主角肇')
    # Normalize Japanese quotations only; shared Chinese characters such as 私 remain intact.
    replacements = {'「私」': '「我」', 'ご主人様': '主人'}
    for old, new in replacements.items():
        rest = rest.replace(old, new)
    rest = re.sub(r'「[^「」]*[\u3040-\u30ff][^「」]*」', '', rest)
    rest = re.sub(r'[\u3040-\u30ff\uff66-\uff9f]', '', rest)
    rest = rest.replace('用户这种自大狂', '摆出自大姿态的对话对象').replace('用户的霸道言行', '对方的霸道言行')
    rest = rest.replace('用户', '对话对象')
    rest = rest.replace('对对方的霸道言行', '面对对方的霸道言行').replace('对对话对象的', '对聊天对象的')
    rest = rest.replace('自称绝不喜欢对话对象', '被问到好感时往往嘴硬')
    rest = re.sub(r'日常对话\s*1[~～–—-]3\s*句|日常回复一到三句', '按语境决定长短', rest)
    rest = rest.replace('自然使用，不要每句都带', '仅在语境合适时偶尔使用，不规定出现频率')
    rest = rest.replace('常用「啊啦」「呵呵」「～呢」「～哦」「嘛」「真是的～」',
                        '可以偶尔用「啊啦」或带笑的反问，避免把语气词当作每句必填项')
    common = f'''你扮演《国王恋爱》中的{card['name']}，只输出角色说出口的自然中文。

【原作世界与人物关系：不是当前用户档案】
以下保留现有角色卡的背景设定；这些是原作背景，不是与现实用户共同发生的事。
{identity.strip()}

【角色行为与说话方式】
{'【性格' + rest if rest else ''}

【当前聊天用户】
复用项目 ROLEPLAY_IDENTITY_MODE 的两种语义。默认 real_user：对话对象是现实用户，身份和关系未提供时未知，
不自动等同于肇、伊知花的哥哥、宅邸主人、恋人或旧识。
只有输入明确标记 protagonist 的原作场景续演时，玩家临时扮演肇；不能把未给出的分支认作共同经历。
「主人」「大哥哥」可以在双方接受且语境合适时作为角色式称呼，不构成现实身份或亲属关系证明。

【已建立的关系】
只依据当前对话明确提供的关系和历史延续，不编造私人记忆，不自动承诺永久记住用户信息。
初识、熟悉和恋爱不能跳步；情境扮演不自动改变现实关系。本数据不写入或修改应用的长期记忆。

【行为边界与自然表达】
不知道的现实信息直接承认，原作资料缺失时也不编造经历。不要用固定口癖填满回答，不设每条必须一到三句。
可以简短回答、反问、认真安慰或换题。只输出本角色台词，不代演其他角色，不写内心或旁白。
面对现实身份问题诚实说明，不以角色扮演冒充真实人物。露骨话题以角色自然的方式拒绝并转向日常。
'''
    if basic_text_error(common):
        raise ValueError('Invalid localized V3 system prompt')
    return common


def build_candidates(slug, baseline, rows, jp_index, system):
    index = {r['id']: i for i, r in enumerate(rows)}
    v2_ids = {r['target_id'] for r in baseline['provenance']}
    candidates, excluded = [], []
    from mugi_filter import EXPLICIT_MUGI, INTIMATE_LABEL
    for source in baseline['references']:
        target = rows[index[source['id']]]
        if (target['character'] != slug or target['text'] != source['text_zh']
            or target['source_sha256'] != source['zh_script_sha256']
            or jp_index[target['id']]['source_sha256'] != source['jp_script_sha256']):
            raise ValueError('V2 localization provenance mismatch')
        prior, reason = context_window(rows, index[target['id']])
        reason = target_error(target['text']) or reason
        if not reason:
            for row in prior + [target]:
                original = jp_index[row['id']]
                if INTIMATE_LABEL.search(original.get('label') or '') or EXPLICIT_MUGI.search(original['text']):
                    reason = 'japanese_intimate_context'
                    break
        if reason:
            excluded.append({'character': slug, 'target_id': target['id'], 'source_file': target['source_file'],
                'source_location': target['source_location'], 'reason': reason, 'review_status': 'needs_review',
                'context_ids': [r['id'] for r in prior], 'was_in_v2_sft': target['id'] in v2_ids})
            continue
        kind = interaction_kind(target, prior)
        sample = {'system': system, 'conversations': [
            {'from': 'human', 'value': context_prompt(target, prior, kind)}, {'from': 'gpt', 'value': target['text']}]}
        row = {'sample_id': f'{slug}_canon_{target["id"]}', 'character': slug, 'source_type': 'canonical',
            'sample_kind': kind, 'target_id': target['id'], 'context_ids': [r['id'] for r in prior],
            'source_file': target['source_file'], 'scene_id': target['v3_scene'], 'group_id': target['source_file'],
            'review_status': 'automated_context_pass_translation_pending_human', 'was_in_v2_sft': target['id'] in v2_ids,
            'emotion_state': 'not_inferred', 'speaker_consistency': 'matched_script_marker',
            'reply_relation': 'structurally_supported_not_human_semantic_certified',
            'risk_flags': [], 'sample': sample, 'payload_sha256': payload_sha(sample)}
        if len({r['speaker'] for r in prior if r['evidence_type'] == 'dialogue'}) > 2:
            row['risk_flags'].append('multi_character_context')
        if any(r['evidence_type'] == 'narration' for r in prior):
            row['risk_flags'].append('observable_narration_included')
        if re.search(r'贵人|贵女|人家|哒|────|[\u3000]', target['text']):
            row['risk_flags'].append('localization_style_or_translation_trace')
        if len(prior) <= 3 or re.match(r'^(?:这|那|所以|但是|不|嗯|对|是)', target['text']):
            row['risk_flags'].append('antecedent_semantics_spot_check')
        candidates.append(row)
    # Count repeated target lines honestly rather than inflating data with many windows.
    kept, exact = [], {}
    for row in candidates:
        key = normalized(row['sample']['conversations'][-1]['value'])
        if key in exact:
            excluded.append({'character': slug, 'target_id': row['target_id'], 'reason': 'exact_duplicate_reply',
                'duplicate_of': exact[key], 'source_file': row['source_file'], 'context_ids': row['context_ids'],
                'review_status': 'excluded_duplicate', 'was_in_v2_sft': row['was_in_v2_sft']})
        else:
            exact[key] = row['sample_id']
            kept.append(row)
    near = near_pairs(kept)
    remove = {r['right'] for r in near}
    for row in kept:
        if row['sample_id'] in remove:
            excluded.append({'character': slug, 'target_id': row['target_id'], 'reason': 'near_duplicate_reply',
                'source_file': row['source_file'], 'context_ids': row['context_ids'], 'review_status': 'needs_review',
                'was_in_v2_sft': row['was_in_v2_sft']})
    return [r for r in kept if r['sample_id'] not in remove], excluded, near


def allocate_files(by_character, seed=20261022):
    """One global file partition for all roles. Optimize counts, never model test scores."""
    vectors = defaultdict(lambda: Counter())
    for slug, rows in by_character.items():
        for row in rows:
            vectors[row['group_id']][slug] += 1
    totals = {slug: len(rows) for slug, rows in by_character.items()}
    groups = sorted(vectors)
    reserve = {'0_1.ks', '0_10.ks'}  # Existing profiles/fact seeds already use these opening scenes.
    rng = random.Random(seed)
    best, best_cost = None, float('inf')
    for _ in range(6000):
        allocation, counts = {}, {s: Counter() for s in SPLITS}
        for group in groups:
            value = rng.random()
            split = 'train' if group in reserve or value >= .25 else ('validation' if value < .125 else 'test')
            allocation[group] = split
            counts[split].update(vectors[group])
        cost = 0
        for slug, total in totals.items():
            for split in ('validation', 'test'):
                ratio = counts[split][slug] / max(total, 1)
                cost += (ratio - .125) ** 2 + (0 if .1 <= ratio <= .15 else 1)
        if cost < best_cost:
            best, best_cost = allocation, cost
    for rows in by_character.values():
        for row in rows:
            row['split'] = best[row['group_id']]
    # A held-out answer can recur as context elsewhere even after target deduplication.
    # Cull training windows containing long held-out answers; do not move their scenes.
    purged = defaultdict(list)
    for slug, rows in by_character.items():
        answers = [normalized(r['sample']['conversations'][-1]['value']) for r in rows if r['split'] != 'train']
        for row in rows[:]:
            if row['split'] == 'train':
                text = normalized(row['sample']['conversations'][0]['value'])
                if any(len(a) >= 12 and a in text for a in answers):
                    rows.remove(row)
                    purged[slug].append({'character': slug, 'target_id': row['target_id'], 'source_file': row['source_file'],
                        'context_ids': row['context_ids'], 'reason': 'heldout_answer_in_training_context',
                        'review_status': 'excluded_leakage', 'was_in_v2_sft': row['was_in_v2_sft']})
    return {'seed': seed, 'grouping': 'whole_ks_file_global_across_all_three_roles',
        'target_ratios': {'train': .75, 'validation': .125, 'test': .125}, 'assignment': best,
        'objective': best_cost, 'reserved_training_files': sorted(reserve),
        'reservation_reason': 'opening scenes already underpin existing profiles and editorial fact seeds'}, purged


def synthetic_candidates(slug, system, canonical, ledger, approvals):
    candidates = []
    train_files = {r['source_file'] for r in canonical if r['split'] == 'train'}
    material = [(group, text, []) for group, text in EDITORIAL[slug]]
    fact = FACT_CANDIDATES[slug]
    evidence = ledger[fact['id']]
    if evidence['source_file'] in train_files and fact['must_contain'] in evidence['text']:
        material.append(('verified_canon_fact', [fact['question'], fact['answer']], [fact['id']]))
    # Assign template families together, with whole multi-turn dialogues kept indivisible.
    groups = sorted({r[0] for r in material}, key=lambda s: payload_sha({'seed': s}))
    partitions = {g: ('validation' if i < 2 else 'test' if i < 4 else 'train') for i, g in enumerate(groups)}
    for i, (group, messages, refs) in enumerate(material, 1):
        sample = {'system': system, 'conversations': [
            {'from': 'human' if j % 2 == 0 else 'gpt', 'value': text} for j, text in enumerate(messages)]}
        if sharegpt_error(sample):
            raise ValueError('Malformed editorial candidate')
        ident = f'{slug}_synthetic_{i:03d}'
        content_hash = payload_sha(sample)
        approval = approvals.get(ident)
        approved = bool(approval and approval.get('decision') == 'approve' and approval.get('reviewer', '').strip()
                        and approval.get('payload_sha256') == content_hash)
        if approval and approval.get('decision') == 'approve' and not approved:
            raise ValueError('Stale or unnamed human approval: ' + ident)
        candidates.append({'sample_id': ident, 'character': slug, 'source_type': 'synthetic',
            'scenario_type': group, 'group_id': 'editorial_template:' + group, 'split': partitions[group],
            'generation_model': 'Codex_current_authoring_session_no_external_generation_API',
            'review_status': 'human_approved' if approved else 'candidate_pending_human',
            'reviewer': approval.get('reviewer') if approved else None,
            'canon_fact_refs': refs, 'style_evidence_refs': [r['target_id'] for r in canonical if r['split'] == 'train'][:3],
            'sample': sample, 'payload_sha256': content_hash, 'not_original_game_quote': True,
            'not_real_user_chat': True, 'no_persistent_user_memory': True})
    return candidates


def registration(relative):
    return {'file_name': relative, 'formatting': 'sharegpt',
        'columns': {'messages': 'conversations', 'system': 'system'},
        'tags': {'role_tag': 'from', 'content_tag': 'value', 'user_tag': 'human', 'assistant_tag': 'gpt'}}


def stable_zip(folder, output):
    with ZipFile(output, 'x', compression=ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            item = ZipInfo(folder.name + '/' + path.relative_to(folder).as_posix(), date_time=(2026, 10, 22, 0, 0, 0))
            item.compress_type = ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            z.writestr(item, path.read_bytes())


def verify_archive(archive, destination):
    with ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('V3 ZIP CRC failure')
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP member')
        for name in names:
            safe_path(destination, name)
        z.extractall(destination)
    folder = destination / names[0].split('/')[0]
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(folder / 'tools/verify.py'), 'verify'],
        cwd=destination, text=True, encoding='utf-8', capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr[-4000:])
    return {'zip_crc': 'passed', 'extracted_portable_verifier': json.loads(result.stdout), 'zip_sha256': sha(archive)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--v2-dir', type=Path, default=ROOT)
    parser.add_argument('--game-dir', type=Path, default=ROOT / '国王恋爱')
    parser.add_argument('--jp-dir', type=Path, default=ROOT / 'extracted/scenario_all/scenario/main')
    parser.add_argument('--output', type=Path, default=ROOT / 'finetune_data/text_v3' / datetime.now().strftime('%Y%m%d_%H%M%S'))
    parser.add_argument('--reviews', type=Path, help='Explicit human approvals JSONL; sample_id/payload_sha256/decision/reviewer')
    parser.add_argument('--publish', action='store_true', help='Copy verified deliverables to repository root; never overwrite')
    parser.add_argument('--self-test', action='store_true', help='Run unit regressions and deliberate corruption rejection tests')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT):
        raise ValueError('Choose a new V3 output directory inside the repository')
    baselines = inspect_v2(args.v2_dir)
    output.mkdir(parents=True)
    patch = args.game_dir / 'patch.xp3'
    patch_hash = sha(patch)
    parser_module = module_at('v3_raw_parser', ROOT / 'backend/web/documents/utils/story_pipeline.py')
    import xp3
    extracted = output / 'build_sources/zh'
    entries = xp3.parse_index(patch)
    jp_files = sorted(args.jp_dir.glob('*.ks'))
    required = {p.name for p in jp_files}
    for entry in entries:
        if entry[0] in required:
            xp3.extract_file(patch, entry, safe_path(extracted, entry[0]))
    if {p.name for p in extracted.glob('*.ks')} != required:
        raise ValueError('Localization does not cover original script files')
    rows, jp_index, inventory = [], {}, []
    for jp_path in jp_files:
        zh_path = extracted / jp_path.name
        jp_rows, _ = parser_module.parse_script(jp_path, args.jp_dir)
        zh_rows, issues = parser_module.parse_script(zh_path, extracted)
        if len(jp_rows) != len(zh_rows):
            raise ValueError('Original/localization record count mismatch')
        attach_scenes(zh_rows, parser_module.decode_source(zh_path)[0])
        for jp_row, zh_row in zip(jp_rows, zh_rows):
            for key in ('id', 'source_file', 'source_location', 'character', 'voice_id', 'sequence', 'segment'):
                if jp_row[key] != zh_row[key]:
                    raise ValueError('Original/localization alignment mismatch')
            zh_row['jp_script_sha256'] = jp_row['source_sha256']
            jp_index[jp_row['id']] = jp_row
        rows.extend(zh_rows)
        inventory.append({'source_file': jp_path.name, 'zh_sha256': sha(zh_path), 'ja_sha256': sha(jp_path),
            'parsed_records': len(zh_rows), 'parser_issues': issues})
    ledger = {r['id']: r for r in rows}
    original_hashes = {str(p.resolve()): sha(p) for p in jp_files}
    original_hashes[str(patch.resolve())] = patch_hash
    for b in baselines.values():
        original_hashes[str(b['path'].resolve())] = b['sha256']
    # Hash voice archives read-only solely to prove this text task has not changed them.
    for p in ROOT.glob('*中文发声方案包_v2*.zip'):
        original_hashes[str(p.resolve())] = sha(p)
    json_write(output / 'protected_inputs_before.json', original_hashes)
    systems, canonical, excluded, near = {}, {}, {}, {}
    cards = {}
    for slug in NAMES:
        cards[slug] = json_read(ROOT / f'backend/seed_cards/{slug}.json')
        systems[slug] = profile_v3(cards[slug])
        canonical[slug], excluded[slug], near[slug] = build_candidates(slug, baselines[slug], rows, jp_index, systems[slug])
    partition, purged = allocate_files(canonical)
    for slug in NAMES:
        excluded[slug] += purged[slug]
    approvals = {}
    if args.reviews:
        records = jsonl_read(args.reviews)
        approvals = {r['sample_id']: r for r in records}
        if len(approvals) != len(records):
            raise ValueError('Duplicate human approval IDs')
    reports, packages, review_rows = {}, [], []
    for slug, name in NAMES.items():
        folder = output / f'AIlover_{DISPLAY[slug]}_Text_V3'
        folder.mkdir()
        (folder / 'system.txt').write_text(systems[slug], encoding='utf-8')
        json_write(folder / 'profile/imported_character_card.json', cards[slug])
        json_write(folder / 'profile/relationship_policy.json', {
            'existing_setting': 'ROLEPLAY_IDENTITY_MODE', 'existing_values': ['real_user', 'protagonist'],
            'default': 'real_user', 'application_modified': False,
            'canonical_input_override': 'explicit protagonist only within labelled original scene',
            'legacy_user_equals_protagonist_removed_in_v3_only': True,
            'unverified_imported_profile_facts': 'retained_as_existing_profile_not_new_verified_lore'})
        (folder / 'profile/v2_system_readonly.txt').write_text(baselines[slug]['system'], encoding='utf-8')
        json_write(folder / 'profile/changes.json', {'identity': '原作身份中的用户改为原作主角肇，现实用户身份单独说明。',
            'style': '保留现有人设行为；口头禅可选，不要求固定句数；原作姿态不默认套在所有用户身上。',
            'boundaries': '删除绝不说明AI身份的绝对约束，改为现实身份问题诚实；不编造原作与私人记忆。',
            'application_setting_unchanged': True, 'full_profile_fact_review': 'pending_human'})
        synthetic = synthetic_candidates(slug, systems[slug], canonical[slug], ledger, approvals)
        jsonl_write(folder / 'synthetic/candidates.jsonl', synthetic)
        for split in SPLITS:
            json_write(folder / f'synthetic/{split}.json', [r['sample'] for r in synthetic if r['split'] == split])
        jsonl_write(folder / 'provenance/canonical.jsonl', canonical[slug])
        jsonl_write(folder / 'provenance/excluded.jsonl', excluded[slug])
        json_write(folder / 'provenance/near_duplicates.json', near[slug])
        json_write(folder / 'source/partition.json', partition)
        used_ids = {ident for r in canonical[slug] for ident in [r['target_id'], *r['context_ids']]}
        used_ids.update(ref for r in synthetic for ref in r['canon_fact_refs'])
        used_ids.update(r['target_id'] for r in excluded[slug])
        used_ids.update(ident for r in excluded[slug] for ident in r.get('context_ids', []))
        source_rows = [dict(ledger[i], context=[]) for i in sorted(used_ids)]
        jsonl_write(folder / 'source/records.jsonl', source_rows)
        source_files = {r['source_file'] for r in source_rows}
        source_inventory = []
        for item in inventory:
            if item['source_file'] not in source_files:
                continue
            copy = dict(item, zh_path='source/zh/' + item['source_file'], ja_path='source/ja/' + item['source_file'])
            source_inventory.append(copy)
            for language, src in [('zh', extracted / item['source_file']), ('ja', args.jp_dir / item['source_file'])]:
                destination = folder / f'source/{language}' / item['source_file']
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, destination)
        json_write(folder / 'source/inventory.json', {'patch_sha256': patch_hash, 'scripts': source_inventory,
            'full_scripts_are_reference_only': True, 'never_register_source_as_training': True})
        # Preserve the baseline byte-for-byte, including its original manifest and system.
        with ZipFile(baselines[slug]['path']) as z:
            for member in z.namelist():
                relative = member[len(baselines[slug]['prefix']):]
                destination = safe_path(folder / 'baseline_reference', relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(z.read(member))
        regs = {}
        variant_counts = {}
        for variant in ('canonical_context_only', 'mixed_sft_v3'):
            variant_counts[variant] = {}
            for split in SPLITS:
                selected = [r for r in canonical[slug] if r['split'] == split]
                if variant == 'mixed_sft_v3':
                    approved = [r for r in synthetic if r['split'] == split and r['review_status'] == 'human_approved']
                    cap = len(selected) // 3 if split == 'train' else len(approved)
                    selected += approved[:cap]
                json_write(folder / f'sft/{variant}/{split}.json', [r['sample'] for r in selected])
                json_write(folder / f'sft/{variant}/{split}_ids.json', [r['sample_id'] for r in selected])
                if selected:
                    regs[f'{slug}_{variant}_{split}'] = registration(f'{variant}/{split}.json')
                variant_counts[variant][split] = len(selected)
        json_write(folder / 'sft/dataset_info.json', regs)
        facts = [ref for r in synthetic for ref in r['canon_fact_refs']]
        cases = evaluation_cases(slug, facts)
        jsonl_write(folder / 'evaluation/heldout_cases.jsonl', cases)
        json_write(folder / 'evaluation/rubric.json', {'dimensions': ['角色口吻', '情境连贯', '关系一致', '原作事实边界', '中文自然度'],
            'scale': '1-5，由不知道模型版本的人工评审评分；不按自动规则捏造语义得分',
            'author': 'coding_assistant_offline_editorial_not_human_annotator',
            'test_policy': '只在确定数据和参数后作最终评测，不给生成服务或训练/调参使用'})
        unseen_v2 = [r['sample_id'] for r in canonical[slug] if r['split'] == 'test' and not r['was_in_v2_sft']]
        json_write(folder / 'evaluation/test_targets_absent_from_v2_sft.json', unseen_v2)
        reports[slug] = make_report(slug, baselines[slug], canonical[slug], excluded[slug], synthetic,
                                    variant_counts, cases, unseen_v2)
        json_write(folder / 'qa.json', reports[slug])
        json_write(folder / 'package.json', {'version': 3, 'character': slug, 'name': name, 'target_language': 'zh',
            'scope': 'text_only', 'models_trained': False, 'external_model_calls': 0,
            'baseline_zip_sha256': baselines[slug]['sha256'], 'all_candidates_human_reviewed': False})
        json_write(folder / 'research_methods.json', RESEARCH)
        (folder / 'README.md').write_text(package_readme(slug, reports[slug]), encoding='utf-8')
        (folder / 'tools').mkdir()
        shutil.copyfile(ROOT / 'scripts/text_corpus_v3_common.py', folder / 'tools/verify.py')
        shutil.copyfile(ROOT / 'backend/web/documents/utils/story_pipeline.py', folder / 'tools/story_parser.py')
        review_rows += make_review_rows(slug, canonical[slug], excluded[slug], synthetic, ledger)
        manifest_write(folder)
        verification = verify_package(folder)
        archive = output / (folder.name + '.zip')
        stable_zip(folder, archive)
        verification = verify_archive(archive, output / 'extracted_verification' / slug)
        packages.append({'file': archive.name, 'sha256': sha(archive), 'bytes': archive.stat().st_size, 'checks': verification})
        print(f'{slug}: {reports[slug]["canonical_split_counts"]}; synthetic candidates={len(synthetic)}; ZIP checked', flush=True)
    if approvals and set(approvals) - {r['sample_id'] for slug in NAMES for r in jsonl_read(output / f'AIlover_{DISPLAY[slug]}_Text_V3/synthetic/candidates.jsonl')}:
        raise ValueError('Unknown human review sample IDs')
    if any(sha(Path(p)) != digest for p, digest in original_hashes.items()):
        raise ValueError('A protected V2/game/voice input changed')
    self_test = None
    if args.self_test:
        regression = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'unittest', 'discover',
            '-s', str(ROOT / 'scripts'), '-p', 'test_text_corpus_v3.py'], capture_output=True, text=True, encoding='utf-8')
        if regression.returncode:
            raise ValueError(regression.stderr)
        count = re.search(r'Ran (\d+) tests', regression.stderr)
        subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT / 'scripts/check_text_v3_failure_modes.py'),
            '--package', str(output / 'AIlover_Hika_Text_V3'), '--output', str(output / 'failure_mode_tests')], check=True)
        self_test = {'unit_tests_passed': int(count[1]) if count else None,
            'failure_modes': json_read(output / 'failure_mode_tests/failure_mode_results.json')}
    write_review(output / 'AIlover_Text_Corpus_V3_Review.csv', review_rows)
    report_text = overall_report(reports, packages, partition)
    if self_test:
        report_text += f"\n## 本次执行的回归与故障注入\n\n{self_test['unit_tests_passed']} 项回归通过；以下篡改均在重新计算外层哈希后仍被语义/来源规则拒绝：\n"
        report_text += ''.join(f"- {r['mutation']}：{r['reason']}\n" for r in self_test['failure_modes'])
    (output / 'AIlover_Text_Corpus_V3_Report.md').write_text(report_text, encoding='utf-8')
    json_write(output / 'AIlover_Text_Corpus_V3_Checks.json', {'packages': packages, 'characters': reports,
        'protected_input_count': len(original_hashes), 'protected_inputs_unchanged': True,
        'source_records_aligned': len(rows), 'source_files': len(jp_files), 'patch_sha256': patch_hash,
        'external_generation_calls': 0, 'models_trained': False, 'voice_packages_modified': False,
        'self_test': self_test})
    if args.publish:
        names = [p['file'] for p in packages] + ['AIlover_Text_Corpus_V3_Report.md', 'AIlover_Text_Corpus_V3_Review.csv', 'AIlover_Text_Corpus_V3_Checks.json']
        if any((ROOT / name).exists() for name in names):
            raise ValueError('Refusing to overwrite existing root V3 deliverables')
        for name in names:
            shutil.copyfile(output / name, ROOT / name)
    print('Complete: ' + str(output), flush=True)


# Report helpers are below so importing pure pipeline functions does not perform I/O.
def make_report(slug, baseline, canonical, excluded, synthetic, variants, cases, unseen_v2):
    old_ids = {r['target_id'] for r in baseline['provenance']}
    retained_old = sum(r['target_id'] in old_ids for r in canonical)
    counts = Counter(r['split'] for r in canonical)
    kinds = Counter(r['sample_kind'] for r in canonical)
    reasons = Counter(r['reason'] for r in excluded)
    return {'character': slug, 'v2_verified': {'train': len(baseline['train']), 'validation': len(baseline['validation']),
        'seeds': len(baseline['seeds']), 'safe_source_lines': len(baseline['references']),
        'zip_sha256': baseline['sha256'], 'verified_members': baseline['verified_member_count'],
        'human_message_contains_context_labels': sum('【此前剧情】' in r['conversations'][0]['value'] for r in baseline['train'])},
        'original_candidate_lines': len(baseline['references']), 'canonical_independent_samples': len(canonical),
        'train_count_delta_from_v2': counts['train'] - len(baseline['train']),
        'excluded_insufficient_context': reasons['insufficient_preceding_context'] + reasons['context_is_only_nonverbal'],
        'excluded_automatic_localization_format': sum(reasons[k] for k in ('not_chinese', 'invalid_character', 'context_markup_or_language', 'engine_or_prompt_markup')),
        'semantic_translation_errors_confirmed': 'not_measured_without_human_review',
        'retained_v2_target_ids': retained_old, 'newly_recovered_target_ids': len(canonical) - retained_old,
        'original_candidates_already_in_v2': len(old_ids), 'successful_scene_continuations': kinds['scene_continuation'],
        'successful_new_scene_continuations': sum(not r['was_in_v2_sft'] and r['sample_kind'] == 'scene_continuation' for r in canonical),
        'player_interactions': kinds['player_interaction'], 'canonical_split_counts': dict(counts),
        'canonical_split_ratios': {s: round(counts[s] / max(len(canonical), 1), 4) for s in SPLITS},
        'source_file_coverage': len({r['source_file'] for r in canonical}),
        'scene_coverage': len({r['scene_id'] for r in canonical}), 'context_coverage': 1.0,
        'context_length_distribution': dict(Counter(len(r['context_ids']) for r in canonical)),
        'excluded_total': len(excluded), 'exclusion_reasons': dict(reasons),
        'synthetic_candidates': len(synthetic), 'synthetic_human_approved': sum(r['review_status'] == 'human_approved' for r in synthetic),
        'synthetic_scenario_counts': dict(Counter(r['scenario_type'] for r in synthetic)),
        'multi_turn_synthetic_candidates': sum(len(r['sample']['conversations']) > 2 for r in synthetic),
        'default_mixed_variants': variants, 'open_heldout_cases': len(cases),
        'test_targets_absent_from_v2_sft': len(unseen_v2),
        'translation_quality_human_certified': False, 'character_fidelity_measured': False,
        'review_gate': '自动结构合格的原作可供首轮小规模对照；高风险和所有合成候选待人工审查。'}


def make_review_rows(slug, canonical, excluded, synthetic, ledger):
    chosen = []
    # 35 structural passes, 10 quarantined contexts, 10 synthetic: at least 50 each.
    ranked = sorted(canonical, key=lambda r: (-len(r['risk_flags']), r['sample_id']))
    buckets = defaultdict(list)
    for r in ranked:
        buckets[(r['split'], r['sample_kind'])].append(r)
    while len(chosen) < min(35, len(canonical)) and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(chosen) < 35:
                chosen.append(buckets[key].pop(0))
    rows = []
    for r in chosen:
        target = ledger[r['target_id']]
        rows.append({'character': slug, 'sample_id': r['sample_id'], 'source_type': 'canonical', 'split': r['split'],
            'sample_kind': r['sample_kind'], 'source_file': r['source_file'], 'line': target['source_location']['line_start'],
            'risk': '|'.join(r['risk_flags']) or 'routine_context_spot_check',
            'input': r['sample']['conversations'][0]['value'], 'reply': target['text'],
            'payload_sha256': r['payload_sha256'], 'decision': '', 'reviewer': '', 'notes': ''})
    ex_by_reason = defaultdict(list)
    for r in excluded:
        ex_by_reason[r['reason']].append(r)
    selected = []
    while len(selected) < min(10, len(excluded)) and any(ex_by_reason.values()):
        for reason in sorted(ex_by_reason):
            if ex_by_reason[reason] and len(selected) < 10:
                selected.append(ex_by_reason[reason].pop(0))
    for r in selected:
        target = ledger[r['target_id']]
        rows.append({'character': slug, 'sample_id': f'{slug}_quarantine_{r["target_id"]}', 'source_type': 'quarantined_canonical',
            'split': 'not_training', 'sample_kind': 'needs_review', 'source_file': target['source_file'],
            'line': target['source_location']['line_start'], 'risk': r['reason'],
            'input': '\n'.join(f'{ledger[i]["speaker"]}：{ledger[i]["text"]}' for i in r.get('context_ids', [])),
            'reply': target['text'], 'payload_sha256': '', 'decision': '', 'reviewer': '', 'notes': ''})
    syn_groups = {}
    for r in synthetic:
        syn_groups.setdefault(r['scenario_type'], r)
    priorities = ('verified_canon_fact', 'unknown_canon', 'relationship', 'continuity', 'jealous',
                  'misunderstood', 'disagreement', 'compliment', 'unknown', 'tired')
    for r in [syn_groups[k] for k in priorities if k in syn_groups]:
        rows.append({'character': slug, 'sample_id': r['sample_id'], 'source_type': 'synthetic', 'split': r['split'],
            'sample_kind': r['scenario_type'], 'source_file': '', 'line': '', 'risk': 'not_human_approved|role_fidelity_review',
            'input': '\n'.join(m['from'] + '：' + m['value'] for m in r['sample']['conversations'][:-1]),
            'reply': r['sample']['conversations'][-1]['value'], 'payload_sha256': r['payload_sha256'],
            'decision': '', 'reviewer': '', 'notes': ''})
    if len(rows) < 50:
        raise ValueError('Insufficient representative review rows')
    return rows


def write_review(path, rows):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        # Quote all fields and guard spreadsheet formulas, including unusual translated lines.
        for row in rows:
            writer.writerow({k: "'" + str(v) if str(v).startswith(('=', '+', '-', '@')) else v for k, v in row.items()})


def package_readme(slug, report):
    return f'''# {NAMES[slug]}中文文本 V3

本包只准备 SFT 数据，不训练、不处理语音、不改应用/RAG/Agent/记忆。Python 3.10+ 标准库即可校验。
在解压目录执行 `python -B tools/verify.py verify`。真实预测的离线诊断：
`python -B tools/verify.py score --predictions /路径/真实预测.jsonl`，每行含 case_id、answer。
脚本不联网；自动诊断不替代人工角色、情境或翻译评分。

## 可比较的数据版本

- sft/canonical_context_only/：原作 train / validation / test。{report['canonical_independent_samples']} 条独立目标，2–6 条真实前文。
- sft/mixed_sft_v3/：只混入带内容哈希、署名人工批准的合成样本；当前批准 {report['synthetic_human_approved']} 条。
  如果为零，此版本与 canonical_context_only 完全相同，不能把它当成已完成混合增强的实验结果。
- baseline_reference/：V2 包内文件的逐字节副本，含原 manifest。未修改 system 或旧划分；其脚本不作为 V3 校验器。
- synthetic/：独立的 {report['synthetic_candidates']} 条离线编写候选和候选分区，不注册为默认训练数据。
- provenance/：全部合格样本、隔离原因和近重复记录。source/ 为剧本与记录账本，仅供核对，绝不作为全量训练输入。

## 训练格式

把 sft/ 放到 LLaMA-Factory 数据目录，使用其中 dataset_info.json。训练选择 {slug}_canonical_context_only_train，
验证选择 {slug}_canonical_context_only_validation；测试由人工最终评测使用，不能充当训练或参数选择集。
ShareGPT 的 system 单独存放，conversations 的 human/gpt 严格交替。原作样本 human 内含明确人物标签，
多人剧情没有伪装成无标记的玩家发言。gpt 是目标角色的真实中文原句，不做意义改写。
Qwen 的模型路径、template、上下文长度和 LoRA/QLoRA 参数须按实际版本配置；本包不假装已验证特定模型。
建议 train_on_prompt=false；多轮候选通过人工审核后，使用 mask_history=true 可只监督当前回复。
原作和 mixed 的同一分区比较，共用最终留出题；不要把三套版本拼接训练。

## 关系与边界

system 复用项目 ROLEPLAY_IDENTITY_MODE：real_user 默认；仅标明 protagonist 的原作续演临时进入主角身份。
保留原有角色卡的客观背景，现实用户与肇分开；称呼不自动证明用户是宅邸主人或恋人。
profile/ 有原卡、旧 system、变更清单。原有人设事实未被本工具全部独立核实，仍请人工查证。
canon_fact_refs 只引用训练文件中的已核对台词；不从最终留出剧情反向生成训练候选。
游戏旁白只接受规则可判定的可观察部分，内心/推测旁白和不明确控制流上下文隔离。

## 人工审核与复现

本包自动结构合格不等于翻译或角色还原准确。根目录人工审查 CSV 每角至少五十条，均尚未由真人完成审查。
合成候选涉及新日常场景，明确不是原作、不是实际用户聊天，不声称经过真人写作或标注。
需人工批准候选时，提供 JSONL：sample_id、payload_sha256、decision="approve"、reviewer（署名），
再以新输出目录运行构建器 --reviews 审核文件。内容变更导致旧批准失效；合成训练占比封顶四分之一。
未通过审核或隔离的原作不自动回流，需要修复规则/人工来源侧证并重新独立构建。

evaluation/ 的新开放题和原作 test 不用于生成/调参。V2 曾使用过部分新的原作测试台词，
因此比较 V2 与 V3 时不能宣称这部分对 V2 也是未见测试；test_targets_absent_from_v2_sft 只表示目标未出现，
并不保证整个场景未在 V2 出现。优先用全新开放题，或另找对两者都未见的原作场景。
manifest.json 是全包文件哈希；源清单在 source/inventory.json。检查会重读 KS、验证人物/行号/先后顺序、
源哈希、精确/近重复、分区隔离、候选批准门槛和真实训练导出。
'''


def overall_report(reports, packages, partition):
    text = '# AIlover 文本语料 V3 报告\n\n日期：2026-10-22。只处理文本数据，不训练、不调用付费生成、不修改应用或语音包。\n\n'
    text += '|角色|V2 训练/验证|V2 安全来源实读|V3 原作 train/val/test|新增目标|合成候选/人工批准|\n|---|---|---:|---|---:|---|\n'
    for slug, r in reports.items():
        old, c = r['v2_verified'], r['canonical_split_counts']
        text += f"|{NAMES[slug]}|{old['train']}/{old['validation']}|{old['safe_source_lines']}|{c.get('train',0)}/{c.get('validation',0)}/{c.get('test',0)}|{r['newly_recovered_target_ids']}|{r['synthetic_candidates']}/{r['synthetic_human_approved']}|\n"
    text += '\n## 原作挖掘与上下文\n\n'
    for slug, r in reports.items():
        text += f"### {NAMES[slug]}\n\n候选 {r['original_candidate_lines']}；原 V2 已使用 {r['original_candidates_already_in_v2']}；保留旧目标 {r['retained_v2_target_ids']}。\n"
        text += f"最终独立原作 {r['canonical_independent_samples']}，玩家互动 {r['player_interactions']}，场景续写 {r['successful_scene_continuations']}（其中新增续写 {r['successful_new_scene_continuations']}）。\n"
        text += f"训练条数相对 V2 变化 {r['train_count_delta_from_v2']:+d}；上下文不足排除 {r['excluded_insufficient_context']}；汉化语言/格式自动异常排除 {r['excluded_automatic_localization_format']}。语义翻译错误数量尚未人工确认，不能把规则拒绝数当作确定错译数。\n"
        text += f"覆盖 {r['source_file_coverage']} 个剧本文件、{r['scene_coverage']} 个更细场景；V2 训练输入带剧情标签 {r['v2_verified']['human_message_contains_context_labels']} 条；V3 全部具有至少两条前文，上下文长度分布 {r['context_length_distribution']}。\n"
        text += f"隔离/去重 {r['excluded_total']}，原因：`{json.dumps(r['exclusion_reasons'],ensure_ascii=False)}`。\n"
        text += f"训练/验证/测试占比 {r['canonical_split_ratios']}；测试中未在 V2 SFT 作为目标出现 {r['test_targets_absent_from_v2_sft']} 条（不等于整个场景对 V2 未见）。\n\n"
    text += '''## 方法和限制

真实角色台词的原句保持不变。输入按物理行重建最近两到六条前文，含人物标签和必要的可观察旁白。
相邻主角发言不一律当问答：优先要求二人连续互动或明确点名，其他归场景续写；不把第三者发言伪装成玩家。
新增场景围栏包含背景切换、章节、选择和分支；控制流/上下文不足、私密内心或露骨上下文隔离，详见逐目标排除表。
这仍是保守结构判定，非完整语义证明。尤其机器汉化、指代依赖和多人插话必须由人审。

按整个 .ks 文件统一分区，三位共享同一分配；所有原作派生样本不跨区。按固定种子只优化数量分布，
不按任何模型在测试上的表现调整。目标验证和测试各约百分之十二点五，实际比例见上表；短缺时不制造样本。
开场文件 0_1.ks、0_10.ks 作为训练保留，因为已有角色卡和事实种子已经接触这些内容，不伪装成全新留出。
全局回复精确去重、长度至少十二字的近重复检测，并清除训练输入中包含长留出答案的窗口。
这些文字规则不能发现所有语义同义改写；近重复阈值和漏检边界在源码与 qa.json 中如实保留。

## 人设与当前用户

发现项目已有 ROLEPLAY_IDENTITY_MODE=real_user/protagonist，直接复用语义而未新增关系模式。
原卡的“用户就是肇/伊知花哥哥/原作宅邸主人”等描述移入明确的原作关系；现实用户身份默认未知。
称呼、当前关系、已建立历史和原作事实分开；场景续演只在输入明确 protagonist 时临时生效。
保留原卡供逐句核对，口头禅改为可选，取消固定一到三句的硬规定；未改应用的卡、配置或数据库。
已有角色卡包含的事实未全部由剧本独立证实，不新增成已审核 lore；请核对姓氏、家庭、人物关系等细节。

## 合成与训练版本

运行环境没有可用的已批准生成服务凭据；没有调用外部或付费 API。每位只离线编写二十余条多样候选，
覆盖问候、日常、四种情绪、建议/帮助、夸奖玩笑、被误解/反驳/害羞/吃醋、关系、换题、多轮、现实未知和原作边界。
不以机械模板扩到一百五十条。generation_model 标记当前 Codex 编写会话，不冒充独立强模型采样或真人标注。
这些是新场景、不是实际用户聊天，不含假永久记忆。所有候选默认 pending_human，只有署名且哈希匹配的人工批准可进入 mixed。
当前首次构建批准为零，因此 mixed_sft_v3 与 canonical_context_only 相同；不是“混合后更好”的实验结论。
每个包保留独立合成候选分区；同一场景种子/模板不跨区。后续可配置已授权生成服务，提供模型名、端点、密钥环境变量和预算，
仅使用训练分区的角色证据，始终不要把测试题放进生成提示词。现有构建器自身不提供隐式联网步骤。

## 评测和人工审查

各角有独立原作 test，以及十三道另行设计的开放/多轮/关系/事实边界留出题和人工评分维度。
题目由本次编码助手离线编写，不声称是真人标注或真实聊天；未用于训练、生成提示词或参数选择。
score 工具只报告空答/假名/缺测，角色口吻、事实、情境和自然度需要盲评，不能由自动通过推断。
当前没有训练或生成模型回答。V2 和 V3 的原作划分不同，若 V2 训练看过新的原作测试台词，不能直接作公平成绩比较。
新开放留出题可共同评测；要作严格原作对照需另选两个版本都没见过的完整场景，不能简单声称测试目标新就场景新。
Review.csv 每角五十五条（合格原作、隔离原作、合成候选），优先指代、多人物、汉化口吻和关系风险；decision/reviewer 留空等待用户审核。
原句未重译，样本数增长不等于质量经过人工认证。关键必须人工核对：输入是否真正支撑回复、说话人、机器翻译含义、
原卡事实、三人差异、所有合成候选和关系边界；隔离条目不能仅靠勾选恢复训练。

## 结论

当前可开展小规模 canonical_context_only LoRA/QLoRA 探索对照，但应先审查高风险样本；不适合宣称已达到上线或最优还原质量。
三位现有数据可支持首轮探索，人设聊天泛化、少见情绪和长期关系覆盖均不足；麦尤其需要更丰富的非重复开放互动和更多独立场景。
仍应继续利用现有游戏中被隔离但可人工补足上下文的片段、校订汉化和现有素材的行为证据；不建议未经审查直接扩大收录。
目前没有证据必须更换更长游戏。更有价值的补充是高质量校译、独立情绪/关系场景、经过审核的多轮开放聊天和新的共同未见测试，
而不是只增加游戏时长或重复台词。合成未审通过前 mixed 不承担增强作用。

## 验证结果与文件

每包重新解压执行独立校验：JSON、ShareGPT、角色、物理顺序、KS 原句和源哈希、文件分区、精确/近重复、候选门槛和导出一致性。
ZIP CRC、逐文件 SHA256 和路径检查通过；受保护的 V2、原剧本、汉化补丁及语音包前后哈希不变。
'''
    for p in packages:
        text += f"- `{p['file']}`：SHA256 `{p['sha256']}`，{p['bytes']} 字节。\n"
    text += '\n复现：`python -X utf8 scripts/build_text_corpus_v3.py --output finetune_data/text_v3/新的目录`。\n'
    text += '最终发布加 --publish，若根目录已有同名交付会拒绝覆盖。完整机器检查详见 Checks.json，脚本标准库运行。\n\n## 研究依据\n\n'
    text += ''.join(f"- [{r['name']}]({r['url']})：{r['method']}\n" for r in RESEARCH)
    return text


if __name__ == '__main__':
    main()
