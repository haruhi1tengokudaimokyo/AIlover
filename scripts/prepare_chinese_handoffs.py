"""Create private Chinese dialogue and cross-lingual voice handoffs, without training/uploading."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

from package_training_handoffs import (ROOT, CHARACTERS, json_file, jsonl_file,
                                     read_rows, load_module, select_sources, manifest)
from chinese_handoff_tools import KANA, sha

PATCH_SHA = '0d220a7f2428048169464050e84b4e8d9244b90da039fdb2167058efe5b3f635'
BLOCKED = re.compile(r'性交|阴茎|阴道|乳头|射精|精液|手淫|口交|肛交|强奸|肉棒|小穴|乳房|下体|高潮|裸体'
    r'|张开.{0,5}腿|身体相通|大人才会.{0,8}事|做.{0,5}大人.{0,8}事|兴奋|脱.{0,8}(?:衣服|内裤)'
    r'|胸部|胸罩|内裤|勃起|发情|床上|侍寝|裙底|接吻|亲嘴|嘴唇|处女|性欲|肉体|插入|抽插|硬起来|身体.{0,5}结合')
SOURCES = {
    'gpt_sovits_cross_language': 'https://github.com/RVC-Boss/GPT-SoVITS/wiki/不同训练集的跨语种能力(Cross‐Language-Ability-of-Different-Training-Sets)',
    'gpt_sovits_api': 'https://github.com/RVC-Boss/GPT-SoVITS/blob/main/api_v2.py',
    'cosyvoice': 'https://github.com/QwenAudio/CosyVoice',
    'cosyvoice_example': 'https://github.com/QwenAudio/CosyVoice/blob/main/example.py',
}


def chinese_ok(text):
    return (isinstance(text, str) and 2 <= len(text.strip()) <= 600
            and bool(re.search(r'[\u4e00-\u9fff]', text))
            and not KANA.search(text) and not BLOCKED.search(text)
            and not re.fullmatch(r'[嗯啊呼哈唔呜喵哼哦呀诶唉\W]+', text)
            and not re.search(r'\[[^\]]+\]|https?://|<\|', text))


def chinese_system(text):
    replacements = {'王様恋愛': '国王恋爱', 'ご主人様': '主人', 'むぎ': '麦', '緋華': '绯华',
                    'お姉ちゃん': '姐姐', 'お姉さん': '姐姐', 'ハジメ': '肇', '「私」': '「我」'}
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r'「[^「」]*[\u3040-\u30ff][^「」]*」', '', text)
    text = KANA.sub('', text)
    text = re.sub(r'([\u4e00-\u9fff]+)（\1）', r'\1', text)
    text = text.replace('（原名麦，也被称作小麦）', '（也被称作小麦）')
    text += ('\n\n【当前对话约束】\n只用自然中文回答。以上原作背景用于理解角色，'
             '不能默认现实用户就是原作主角或经历了原作事件；关系进展以真实对话为准。')
    return text


def pair_examples(rows, safe_jp, slug, system, safe_input_ids=None):
    allowed = {r['id'] for r in safe_jp}
    pairs, seen, rejected = [], set(), Counter()
    previous = None
    for row in rows:
        if previous and (row['source_file'], row['segment']) != (previous['source_file'], previous['segment']):
            previous = None
        if row['id'] in allowed:
            if not previous or previous['speaker'] != '肇':
                rejected['no_adjacent_protagonist_turn'] += 1
            elif (not chinese_ok(row['text']) or not chinese_ok(previous['text'])
                  or (safe_input_ids is not None and previous['id'] not in safe_input_ids)):
                rejected['chinese_text_quality'] += 1
            else:
                key = (previous['text'], row['text'])
                if key in seen:
                    rejected['duplicate_pair'] += 1
                else:
                    seen.add(key)
                    pairs.append({'sample': {'system': system, 'conversations': [
                        {'from': 'human', 'value': key[0]}, {'from': 'gpt', 'value': key[1]}]},
                        'source_file': row['source_file'], 'input_id': previous['id'], 'target_id': row['id'],
                        'input_line': previous['source_location'], 'target_line': row['source_location'],
                        'chinese_script_sha256': row['source_sha256'], 'voice_id': row['voice_id']})
        if row['evidence_type'] == 'dialogue':
            previous = row
    groups = sorted({r['source_file'] for r in pairs}, key=lambda s: hashlib.sha256(s.encode()).hexdigest())
    validation_files = set(groups[:max(1, len(groups) // 10)])
    train = [r for r in pairs if r['source_file'] not in validation_files]
    targets = {r['sample']['conversations'][1]['value'] for r in train}
    validation = []
    for row in pairs:
        if row['source_file'] in validation_files:
            if row['sample']['conversations'][1]['value'] in targets:
                rejected['validation_target_overlap'] += 1
            else:
                validation.append(row)
    if not train or not validation:
        raise ValueError('No usable independent train/validation split')
    return train, validation, dict(rejected)


def base(folder, slug, kind):
    folder.mkdir(parents=True)
    shutil.copyfile(ROOT / 'scripts/chinese_handoff_tools.py', folder / 'handoff.py')
    json_file(folder / 'package.json', {'name': CHARACTERS[slug], 'slug': slug, 'kind': kind,
        'version': 2, 'target_language': 'zh', 'original_audio_language': 'ja',
        'models_trained': False, 'private_local_handoff': True, 'patch_sha256': PATCH_SHA})
    json_file(folder / 'technical_sources.json', {'consulted': '2026-10-22', 'sources': SOURCES})


def text_package(folder, slug, jp, cn, safe):
    base(folder, slug, 'text')
    module = load_module('original_sharegpt', ROOT / 'finetune_data/llm/build_sharegpt.py')
    card = json.loads((ROOT / f'backend/seed_cards/{slug}.json').read_text(encoding='utf-8'))
    system = chinese_system(module.profile_to_system(card['profile'], card['name']))
    from mugi_filter import mugi_training_usable
    safe_input_ids = {r['id'] for r in jp if mugi_training_usable(r)}
    train, validation, rejected = pair_examples(cn, safe, slug, system, safe_input_ids)
    for split, rows in [('train', train), ('validation', validation)]:
        json_file(folder / f'sft/{split}.json', [r['sample'] for r in rows])
        jsonl_file(folder / f'provenance/{split}.jsonl', [dict(r, sample_index=i, sample=None) for i, r in enumerate(rows)])
    seeds = [{'system': system, 'conversations': [{'from': 'human', 'value': u}, {'from': 'gpt', 'value': a}]}
             for u, a in module.parse_seed_examples(card['profile'], card['name'])]
    if len(seeds) != 5 or any(not chinese_ok(c['value']) for r in seeds for c in r['conversations']):
        raise ValueError('Invalid Chinese role seeds')
    json_file(folder / 'sft/seed_samples.json', seeds)
    from training_handoff_tools import registration
    json_file(folder / 'sft/dataset_info.json', {f'ousama_{slug}_zh_{s}': registration(f'{s}.json')
        for s in ('train', 'validation', 'seed_samples')})
    (folder / 'system.txt').write_text(system, encoding='utf-8')
    index = {r['id']: r for r in cn}
    safe_ids = {r['id'] for r in safe}
    pairs = []
    for source in safe:
        target = index[source['id']]
        if chinese_ok(target['text']):
            pairs.append({'id': source['id'], 'character': slug, 'text_zh': target['text'],
                'text_ja_reference_only': source['text'], 'voice_id': source['voice_id'],
                'source_file': source['source_file'], 'source_location': source['source_location'],
                'jp_script_sha256': source['source_sha256'], 'zh_script_sha256': target['source_sha256'],
                'preceding_context_zh': [dict(c, text=index[c['id']]['text']) for c in source['context']
                    if chinese_ok(index[c['id']]['text'])]})
    jsonl_file(folder / 'reference_only/aligned_localization.jsonl', pairs)
    report = {'aligned_role_records': sum(r['character'] == slug for r in cn), 'safe_zh_reference_lines': len(pairs),
        'train_samples': len(train), 'validation_samples': len(validation), 'separate_handwritten_seeds': len(seeds),
        'train_files': sorted({r['source_file'] for r in train}),
        'validation_files': sorted({r['source_file'] for r in validation}), 'rejected': rejected,
        'full_human_translation_review': False, 'translation_source': 'user_supplied_localization_patch',
        'machine_translation_patch_indicated_by_backup_name': True, 'kana_in_sft': 0,
        'all_original_japanese_datasets_unchanged': True, 'mock_translations': 0}
    json_file(folder / 'qa.json', report)
    (folder / 'README_先读我.md').write_text(f'''# {CHARACTERS[slug]}：中文对话训练包 v2

本次读取游戏 patch.xp3 的汉化，不再把日文待翻译数据当作中文训练集。
中文训练 {len(train)} 条、独立验证 {len(validation)} 条、另存角色卡中文改写示例 5 条。
只有相邻的主角发言→本角色回答进入 SFT；不捏造通用提问来拼接不相关台词。
旁白可跳过，但不跨文件、分段或其他角色的对话；输入不包含目标答案或未来台词。
按剧本文件切分训练和验证，剔除验证中与训练相同的回答，避免明显泄漏。

## 使用

1. 解压后运行 `python handoff.py verify`，Python 3.10+，无额外依赖。
2. 将 sft/ 导入 LLaMA-Factory 数据目录。训练数据名 ousama_{slug}_zh_train，验证名 ousama_{slug}_zh_validation。
3. template 按所选中文能力良好的指令底模匹配，先小规模 LoRA 对照，避免过拟合；不得合并验证集训练。
4. seed_samples 单独标记为人工角色卡改写，不是游戏逐句汉化，也不默认复制多次提高权重。
5. 比较底模与微调模型：中文一致性、人设、自然接话、现实知识诚实度、未经历原剧情时是否乱认亲。
   游戏主角与角色已有关系，线上不要把剧情关系强加给新用户；不适合直接回答的剧情片段留在来源参考。

## 质量边界

汉化补丁备份文件名显示它可能由机器翻译产生；已做结构对齐、原文过滤、中文过滤、去重和分组验证，
尚未逐条人工校译，不能称为经过人工精修的最优数据。建议先人工抽查各文件和验证集，再训练对照。
reference_only/ 保留中日对应和行号/hash，日文只供核对，不注册训练。
SFT 的 system、human、gpt 均无日文假名；无旧 mock 翻译、空训练集、API 密钥或聊天数据库。
本包不训练语音；语音须用另一个中文发声方案包。模型尚未训练，数据校验不等于效果验收。
''', encoding='utf-8')
    return report


def evaluation_lines():
    texts = [
        '早上好，今天也请多多关照。', '你回来啦，我刚好泡好了茶。', '先坐下来休息一下，晚饭马上就好。',
        '别逞强，累了就告诉我。', '这件事我不太清楚，我们一起查一查吧。', '今天过得怎么样，有什么想和我说的吗？',
        '嗯，我在听，你慢慢说。', '我有点生气，但还是想先听你的解释。', '真的吗？那可太让人高兴了！',
        '没关系，我们明天再试一次。', '门口的伞记得带上，外面可能会下雨。', '请把这本书放回左边第二层书架。',
        '现在是下午三点十五分。', '一共二十三元五角，请收好零钱。', '十月二十二日，星期四，我们约好见面。',
        '我买了苹果、葡萄、橘子，还有一小盒草莓。', '厨房里炖着汤，小心别碰到烫手的锅。',
        '吃饭之前要洗手，吃完之后一起收拾。', '窗外的风吹动了浅蓝色的窗帘。', '你说得有道理，不过我还有另一种想法。',
        '等一下，这里好像哪里不对。', '你确定吗？可不要又拿我开玩笑。', '知道啦，我会记得提醒你的。',
        '谢谢你愿意告诉我这些。', '那个问题，我现在还没有答案。', '这不是你的错，先别急着责备自己。',
        '我想吃一碗热腾腾的面，再加一个鸡蛋。', '从这里直走，经过路口以后向右转。',
        '今天的练习先到这里，记得让眼睛休息。', '明天早一点出发，路上就不用那么着急。',
        '你刚才说的是重新开始，还是继续上一次的进度？', '如果你愿意，我可以陪你安静地待一会儿。',
        '别偷偷笑，我可是很认真地在说。', '哼，这次就算你说得对。', '好吧，那我们拉钩，说好了。',
        '生日快乐，希望你今天能过得开心。', '夜已经深了，把灯调暗一点吧。', '晚安，愿你做个轻松的好梦。',
        '这杯茶有一点苦，回味却很清甜。', '先确认地址，再检查时间，最后带上钥匙。',
    ]
    return [{'id': f'zh_{i:03d}', 'text': text, 'purpose': 'pronunciation_and_daily_emotion'}
            for i, text in enumerate(texts, 1)]


def voice_package(folder, slug, previous, source_files):
    base(folder, slug, 'voice')
    metadata = read_rows(previous / 'provenance/labels.jsonl')
    refs = json.loads((previous / 'reference/provenance.json').read_text(encoding='utf-8'))
    ref_ids = {r['voice_id'] for r in refs}
    candidates = [r for r in metadata if r['voice_id'] not in ref_ids
                  and 3 <= r['duration_seconds'] <= 10 and r['rms'] >= 800 and r['peak_ratio'] < .98]
    # Interleave script groups so one short scene cannot fill the entire adaptation subset.
    groups = defaultdict(list)
    for row in sorted(candidates, key=lambda r: sha(previous / f"dataset/{slug}/{r['voice_id']}.wav")):
        groups[source_files[row['source_ids'][0]]].append(row)
    selected, seconds = [], 0
    while any(groups.values()):
        for key in sorted(groups):
            if groups[key]:
                row = groups[key].pop()
                if seconds + row['duration_seconds'] <= 600:
                    selected.append(row)
                    seconds += row['duration_seconds']
    if seconds < 540:
        raise ValueError('Insufficient clean optional adaptation material')
    lines = []
    for row in selected:
        relative = f"dataset/{slug}/{row['voice_id']}.wav"
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(previous / relative, target)
        lines.append(f"{relative}|{slug}|ja|{row['text']}")
    (folder / 'labels').mkdir()
    (folder / 'labels/fewshot_10min_ja.list').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    shutil.copytree(previous / 'reference', folder / 'reference')
    jsonl_file(folder / 'provenance/optional_adaptation.jsonl', selected)
    jsonl_file(folder / 'chinese_eval/utterances.jsonl', evaluation_lines())
    (folder / 'chinese_eval/人工验收表.csv').write_text(
        'case_id,音色相似度一到五,自然度一到五,中文是否清楚,是否夹日语,漏读重复,备注\n' +
        ''.join(f"{r['id']},,,,,,\n" for r in evaluation_lines()), encoding='utf-8-sig')
    (folder / 'cosyvoice_crosslingual.py').write_text('''"""Run from an installed official CosyVoice repository; no downloads performed here."""
import argparse
from pathlib import Path
import torchaudio
from cosyvoice.cli.cosyvoice import AutoModel

p = argparse.ArgumentParser()
p.add_argument('--model-dir', required=True)
p.add_argument('--reference', required=True)
p.add_argument('--text', required=True)
p.add_argument('--output-dir', required=True)
a = p.parse_args()
out = Path(a.output_dir)
out.mkdir(parents=True, exist_ok=True)
model = AutoModel(model_dir=a.model_dir)
for i, result in enumerate(model.inference_cross_lingual(a.text, a.reference, stream=False)):
    torchaudio.save(str(out / f'zh_{i:03d}.wav'), result['tts_speech'], model.sample_rate)
''', encoding='utf-8')
    report = {'optional_adaptation_clips': len(selected), 'optional_adaptation_minutes': round(seconds / 60, 3),
        'reference_clips': len(refs), 'actual_chinese_audio_files': 0, 'evaluation_chinese_sentences': 40,
        'inference_run': False, 'audio_manually_listened': False, 'source_audio_language': 'ja',
        'target_output_language': 'zh', 'reference_excluded_from_adaptation': True,
        'default_method': 'pretrained_cross_lingual_zero_shot', 'optional_method': 'small_ja_adaptation_ab_test'}
    json_file(folder / 'qa.json', report)
    (folder / 'README_先读我.md').write_text(f'''# {CHARACTERS[slug]}：保留原音色、中文发声方案 v2

目标是中文对话、中文发声；来源游戏没有中文录音。日文参考音频只提供音色条件，不能改标成中文录音。
默认先用预训练多语种模型做跨语言零样本推理，试听通过才考虑微调。
本包提供三组日常原音参考、约十分钟可选日文适配素材，以及四十条中文验收句。
音频为单声道、三万二千赫兹、十六位 PCM；参考文本对应真实日文读音，prompt_lang=ja，text_lang=zh。
这些素材不是中文配音数据；没有生成中文音频，也没有执行模型训练或试听验收。

## 首选：先试听跨语言基线

可对比 CosyVoice 三代与 GPT-SoVITS 的多语种预训练底模，用三组参考分别生成同一批中文句子。
CosyVoice 官方提供 inference_cross_lingual；附 cosyvoice_crosslingual.py 为官方示例接口的适配。
在按官方说明安装好的 CosyVoice 仓库中执行（把路径换成实际位置）：
`python /交接包/cosyvoice_crosslingual.py --model-dir /模型目录 --reference /交接包/reference/{slug}_ref_1.wav --text "你好，今天过得怎么样？" --output-dir /输出目录`
依赖和模型由训练操作者按照上游文档安装，本包不下载权重。先用官方多语种预训练模型，不加载旧的大量日文微调权重。

GPT-SoVITS 方案：本包和服务部署在同一台机器。按官方 api_v2.py 启动服务，加载多语种底模。
`python handoff.py verify`：离线校验。
`python handoff.py request --text "你好，今天过得怎么样？"`：仅打印请求，不联网。
`python handoff.py synthesize --text "你好，今天过得怎么样？" --reference 1`：显式调用本机端口 9880 的 /tts，保存到 generated/。
服务必须能读取请求内参考音频的实际绝对路径；远程服务需要部署端自行适配路径，本工具只调用 localhost。

## 可选：少量日文适配对照

当零样本音色不足时，再试本包 {len(selected)} 段、{seconds / 60:.2f} 分钟日文适配，并与未微调基线比较。
`python handoff.py paths` 生成当前机器路径的 train_optional_ja.list，语种保持 ja。
不默认使用旧包数小时的纯日文全量微调。GPT-SoVITS 作者记录指出，大量单语微调可能覆盖跨语言能力。
作者文档的分钟数是其对应版本的经验，不能保证所有新版本效果。训练参数遵循实际模型版本。
参考音频不加入适配训练；中文验收集也不能冒充训练录音。

## 验收后才能选方案

对 chinese_eval/utterances.jsonl 全部四十句生成音频，至少用三组参考对比音色、中文发音、日语口音、漏读重复、长句和情绪。
人工听评填 CSV；另用真实中文 ASR 结果创建 JSONL，每行含 id、asr_text。
`python handoff.py evaluate --transcripts 实际识别结果.jsonl` 输出 CER 和缺测数。
禁止把期望文本直接复制成 ASR 结果；未测句数、音色和自然度不能冒充通过。
建议完整四十句、无夹日语、无明显重复漏读，中文 CER 不高于百分之五且人工音色/自然度平均至少四分作为项目起始门槛。
这些是本项目建议门槛，不是模型厂商保证，也不是仅靠 CER 就能认定音色相同。
技术来源见 technical_sources.json。没有真实生成与试听，因此目前只能交付可执行实验材料，不能承诺“原声无损中文”。
''', encoding='utf-8')
    return report


def verify_zip(path, destination):
    with ZipFile(path) as z:
        if z.testzip():
            raise ValueError('ZIP CRC failure')
        names = z.namelist()
        if len(names) != len(set(names)) or any('..' in Path(n).parts or ':' in n or n.startswith('/') or '\\' in n for n in names):
            raise ValueError('Invalid ZIP entry')
        prefix = names[0].split('/')[0] + '/'
        info = json.loads(z.read(prefix + 'manifest.json'))
        if set(names) != {prefix + p for p in info['files']} | {prefix + 'manifest.json'}:
            raise ValueError('Manifest coverage mismatch')
        for name, expected in info['files'].items():
            data = z.read(prefix + name)
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise ValueError('ZIP member checksum mismatch')
        z.extractall(destination)
    folder = destination / prefix.rstrip('/')
    commands = [['verify']]
    if json.loads((folder / 'package.json').read_text(encoding='utf-8'))['kind'] == 'voice':
        commands += [['paths'], ['request', '--text', '你好，今天过得怎么样？']]
    checks = []
    for command in commands:
        result = subprocess.run([sys.executable, '-X', 'utf8', str(folder / 'handoff.py'), *command], cwd=destination,
                                capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise ValueError(result.stderr[-2000:])
        checks.append({'command': command, 'result': json.loads(result.stdout)})
    return {'CRC': 'passed', 'all_member_sha256': 'passed', 'extracted_commands': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stamp', default=datetime.now().strftime('%Y%m%d_%H%M%S'))
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9_]+', args.stamp):
        parser.error('Invalid stamp')
    patch = ROOT / '国王恋爱/patch.xp3'
    if sha(patch) != PATCH_SHA:
        raise ValueError('Chinese patch changed; alignment must be audited again')
    import xp3
    extraction = ROOT / 'extracted/chinese_patch_20261022'
    for entry in xp3.parse_index(patch):
        if entry[0].endswith('.ks'):
            relative = Path(entry[0])
            if relative.is_absolute() or '..' in relative.parts or ':' in entry[0] or '\\' in entry[0]:
                raise ValueError('Unsafe patch script path')
            xp3.extract_file(patch, entry, extraction / relative)
    jp = read_rows(ROOT / 'backend/story_data/records.jsonl')
    examples = read_rows(ROOT / 'backend/story_data/dialogue_examples.jsonl')
    pipeline = load_module('chinese_story_pipeline', ROOT / 'backend/web/documents/utils/story_pipeline.py')
    cn = []
    for filename in sorted({r['source_file'] for r in jp}):
        parsed, _ = pipeline.parse_script(ROOT / 'extracted/chinese_patch_20261022' / filename,
                                          ROOT / 'extracted/chinese_patch_20261022')
        cn.extend(parsed)
    index = {r['id']: r for r in cn}
    for row in jp:
        target = index[row['id']]
        for key in ('source_file', 'source_location', 'character', 'voice_id', 'segment', 'sequence'):
            if row[key] != target[key]:
                raise ValueError(f'Alignment mismatch: {row["id"]} {key}')
    if len(jp) != len(cn) or len(index) != len(cn):
        raise ValueError('Duplicate/missing Chinese records')
    staging = ROOT / 'share/training-handoff' / ('zh-v2-' + args.stamp)
    staging.mkdir(parents=True, exist_ok=False)
    archives = []
    for slug, name in CHARACTERS.items():
        safe = select_sources(jp, examples, slug)
        for kind, label in [('text', '中文对话训练'), ('voice', '中文发声方案')]:
            folder = staging / f'AIlover_{slug}_{kind}_zh_v2'
            summary = text_package(folder, slug, jp, cn, safe) if kind == 'text' else voice_package(folder, slug,
                ROOT / f'share/training-handoff/20261022_193805/AIlover_{slug}_voice',
                {r['id']: r['source_file'] for r in jp})
            manifest(folder)
            archive = ROOT / f'AIlover_{name}_{label}包_v2_{args.stamp}.zip'
            with ZipFile(archive, 'x', ZIP_DEFLATED, compresslevel=6) as z:
                for path in sorted(folder.rglob('*')):
                    if path.is_file():
                        z.write(path, path.relative_to(staging).as_posix())
            checks = verify_zip(archive, staging / 'extracted-checks' / f'{slug}-{kind}')
            archives.append({'file': archive.name, 'sha256': sha(archive), 'bytes': archive.stat().st_size,
                             'slug': slug, 'kind': kind, 'summary': summary, 'checks': checks})
            print(f'Checked {archive.name}', flush=True)
    baseline = ROOT / 'extracted/characters/mugi/existing_data_before.json'
    unchanged = all(sha(ROOT / r['path']) == r['sha256'] for r in json.loads(baseline.read_text(encoding='utf-8')))
    if not unchanged:
        raise ValueError('An original dataset changed')
    json_file(ROOT / f'AIlover_全中文方案_校验_{args.stamp}.json', {'archives': archives,
        'patch_sha256': PATCH_SHA, 'aligned_original_records': len(jp), 'original_dataset_hashes_unchanged': unchanged,
        'external_api_calls': 0, 'models_trained': False, 'actual_chinese_audio_generated': 0})
    overview = '# 全中文对话与原音色中文发声：请使用 v2 包\n\n'
    overview += '之前忽略了汉化 patch.xp3，旧包并不适合直接实现全中文目标。本次已按台词 ID 对齐真正汉化文本。\n\n'
    overview += '|角色|中文训练 / 验证|文本包|原音色中文发声方案包|\n|---|---|---|---|\n'
    for slug, name in CHARACTERS.items():
        text, voice = [r for r in archives if r['slug'] == slug]
        overview += f"|{name}|{text['summary']['train_samples']} / {text['summary']['validation_samples']}|[{text['file']}]({text['file']})|[{voice['file']}]({voice['file']})|\n"
    overview += '''\n每个包都有 README、独立 Python 工具和 SHA256 清单；六包均已解压运行校验，ZIP CRC 和所有成员哈希通过。
文本包可以进入中文 SFT 训练准备；汉化可能是机器翻译，仍需人工校译和微调对照，不能称为已验证最优。
语音包默认跨语言零样本推理，三组真实日文音色参考、可选约十分钟小量适配、四十句中文验收。
用户没有中文配音录音，中文音频文件数为零；不能把日文音频的文本标成中文来冒充中文训练数据。
目前没有训练或实际生成试听；保留音色的程度、中文口音和自然度需要按包内流程验收。
旧日文交接包移至 share/training-handoff/previous-ja-20261022_193805/ 保留，原始训练材料未改。
技术依据：
'''
    overview += ''.join(f'- [{key}]({url})\n' for key, url in SOURCES.items())
    (ROOT / f'AIlover_全中文方案_先看这里_{args.stamp}.md').write_text(overview, encoding='utf-8')


if __name__ == '__main__':
    main()
