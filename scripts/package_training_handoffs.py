"""Build six private local handoffs, then extract and verify every archive.

Does not change original datasets, translate remotely, or upload anything.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave
from zipfile import ZipFile, ZIP_DEFLATED

from build_character_data import clean_text
from mugi_filter import mugi_training_usable
from training_handoff_tools import digest, registration, MUTABLE

ROOT = Path(__file__).resolve().parents[1]
CHARACTERS = {'hika': '绯华', 'ayame': '菖蒲', 'mugi': '麦'}
REFERENCES = {'hika': ('vo2_0050', 'vo2_0054', 'vo2_0062'),
              'ayame': ('vo8_0023', 'vo8_0024', 'vo8_0027'),
              'mugi': ('vo1_0002', 'vo1_0262', 'vo1_0032')}


def json_file(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def jsonl_file(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def select_sources(all_rows, examples, slug):
    index = {row['id']: row for row in all_rows}
    result = []
    for example in examples:
        if example['character'] != slug:
            continue
        raw = index[example['id']]
        if not mugi_training_usable(raw):
            continue
        context = []
        for nearby in raw['context']:
            old = index[nearby['id']]
            if (old['source_file'] == raw['source_file'] and old['segment'] == raw['segment']
                    and old['sequence'] < raw['sequence'] and mugi_training_usable(old)):
                context.append(dict(nearby, text=clean_text(old['text'])))
        result.append(dict(raw, text=clean_text(raw['text']), character=slug,
                           context=context, evidence_type='style', reviewed=False))
    if not result or len({row['id'] for row in result}) != len(result):
        raise ValueError('Empty/duplicate character source IDs')
    return result


def choose_voice_labels(labels, allowed, slug):
    variants = defaultdict(set)
    for path, character, language, text in labels:
        if character != slug or language != 'ja' or not text:
            raise ValueError('Wrong speaker/language in original labels')
        variants[Path(path).stem].add(text)
    seen, selected, excluded = set(), [], Counter()
    for path, _, _, text in labels:
        stem = Path(path).stem
        if len(variants[stem]) > 1:
            excluded['conflicting_transcripts'] += 1
        elif (stem, text) not in allowed:
            excluded['not_in_curated_source'] += 1
        elif stem in seen:
            excluded['identical_duplicate'] += 1
        else:
            seen.add(stem)
            selected.append((stem, text))
    return selected, dict(excluded)


def manifest(folder):
    files = {}
    for path in sorted(folder.rglob('*')):
        if path.is_file() and path.name != 'manifest.json':
            relative = path.relative_to(folder).as_posix()
            files[relative] = {'bytes': path.stat().st_size, 'sha256': digest(path),
                               'mutable_after_handoff': relative in MUTABLE}
    json_file(folder / 'manifest.json', {'hash': 'SHA256', 'files': files})


def base_package(folder, slug, kind):
    folder.mkdir(parents=True)
    shutil.copyfile(ROOT / 'scripts/training_handoff_tools.py', folder / 'handoff.py')
    json_file(folder / 'package.json', {'name': CHARACTERS[slug], 'slug': slug, 'kind': kind,
              'language_of_game_material': 'ja', 'models_trained': False, 'private_local_handoff': True})


def text_package(folder, slug, sources, legacy):
    base_package(folder, slug, 'text')
    module = load_module('original_sharegpt', ROOT / 'finetune_data/llm/build_sharegpt.py')
    card = json.loads((ROOT / 'backend/seed_cards' / (slug + '.json')).read_text(encoding='utf-8'))
    system = module.profile_to_system(card['profile'], card['name'])
    seeds = [{'system': system, 'conversations': [{'from': 'human', 'value': user}, {'from': 'gpt', 'value': reply}]}
             for user, reply in module.parse_seed_examples(card['profile'], card['name'])]
    if len(seeds) != 5:
        raise ValueError('Expected five Chinese adaptation examples')
    json_file(folder / 'character_card.json', card)
    (folder / 'system.txt').write_text(system, encoding='utf-8')
    glossary = ROOT / ('finetune_data/mugi/llm/glossary.json' if slug == 'mugi' else 'finetune_data/llm/glossary.json')
    shutil.copyfile(glossary, folder / 'glossary.json')
    jsonl_file(folder / 'source/dialogue_examples.jsonl', sources)
    jsonl_file(folder / 'reference_only/legacy_lines_clean.jsonl', legacy)
    json_file(folder / 'output/seed_samples.json', seeds)  # A JSON array, not legacy JSONL mislabeled .json.
    json_file(folder / 'output/sharegpt.json', [])
    json_file(folder / 'output/dataset_info.json', {f'ousama_{slug}_seed': registration('seed_samples.json')})
    json_file(folder / 'qa.json', {'japanese_source_records': len(sources), 'legacy_reference_records': len(legacy),
              'chinese_adaptation_seeds': 5, 'real_translated_corpus_records': 0,
              'old_mock_samples_included': 0, 'context_policy': 'same file/segment, strictly preceding target',
              'curation_policy': 'legacy token filter plus intimate scene/nonverbal/precise expression filter',
              'reference_only_is_not_training_input': True})
    readme = f'''# {CHARACTERS[slug]}（{slug}）文本训练交接包

## 状态必须先看

本包有 {len(sources)} 条日文待翻译来源，5 条中文人工角色卡改写示例。
完整中文语料尚未翻译，模型尚未训练；5 条示例不能代表足够的全量微调数据。
旧全局目录的 mock 翻译/占位 ShareGPT 没有装入此包。`output/sharegpt.json` 初始为空，不注册空语料。
`reference_only/` 只是原有清洗材料的保全副本，可能保留旧规则未过滤的片段，不直接进入训练。
新来源使用更保守的逐行/场景/非语言过滤，不能等同于逐条人工审查。

## 交给下一位操作者

1. 整包解压到任意目录，使用 Python 3.10+，先运行 `python handoff.py verify` 校验。
2. 如使用 API 翻译，安装 `pip install openai`；只在自己机器设置环境变量 `API_KEY`、可选 `API_BASE`。
   本包没有密钥、账号、数据库、机器绝对路径或自动联网的启动步骤。
3. 显式试翻：`python handoff.py translate --model 你的模型名 --limit 20`。
   此命令才会调用付费/外部服务。审阅译文后去掉 `--limit 20` 继续；仅跳过验证合格的记录。
4. 也可人工提供同结构 `output/translated.jsonl`，离线转换：`python handoff.py convert`。
   格式需包含 id、character、source_file、source_sha256、text_src、text_zh、context_zh。
   context_zh 按来源前文的 id/speaker 原样对齐，text 填中文。source_sha256 从来源记录复制。
5. 查看 `output/build_report.json` 的拒绝原因/完成率，人工复查译文。错误行不会把整批转换打断。
6. 将 `output/` 下真正有内容的训练 JSON 与 `dataset_info.json` 交给 LLaMA-Factory；
   注册名 `ousama_{slug}_seed`，真实译稿非空后才生成 `ousama_{slug}_corpus`。
   基座、template、显存、LoRA 参数按训练环境配置，不能由这些数据的通过质检推断模型效果。

## 内容与边界

character_card.json / system.txt：角色人设；中文示例是改写，不是游戏逐句译文。
source/：带原文 ID、行号、文件哈希和前文的日文数据；不泄漏目标/未来台词进输入。
glossary.json：人物译名与称呼对照。
manifest.json：原始交付文件 SHA256；转换生成的 sharegpt/dataset_info/build_report 是允许变化的输出。
校验默认检查不变的输入/工具/seed。日文原文只用于本地交接；没有执行模型训练或声音克隆。
'''
    (folder / 'README_先读我.md').write_text(readme, encoding='utf-8')
    return {'source_records': len(sources), 'seed_samples': 5, 'real_translated_records': 0}


def voice_package(folder, slug, sources, tts):
    base_package(folder, slug, 'voice')
    original = ROOT / ('finetune_data/mugi/tts' if slug == 'mugi' else 'finetune_data/tts')
    labels = [line.split('|', 3) for line in (original / (slug + '.list')).read_text(encoding='utf-8').splitlines()]
    allowed = {(row['voice_id'], tts.clean_text(row['text'])) for row in sources if row.get('voice_id')}
    selected, excluded = choose_voice_labels(labels, allowed, slug)
    if not selected:
        raise ValueError('No usable voice labels')
    dataset = folder / 'dataset' / slug
    dataset.mkdir(parents=True)
    durations, details, high_peaks = [], {}, []
    lines = []
    source_ids = defaultdict(list)
    for row in sources:
        source_ids[(row.get('voice_id'), tts.clean_text(row['text']))].append(row['id'])
    for stem, text in selected:
        source = original / 'dataset' / slug / (stem + '.wav')
        with wave.open(str(source), 'rb') as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 32000):
                raise ValueError('Bad voice audio format')
        duration, rms, peak, _ = tts.wav_info(source)
        if not (2 <= duration <= 15) or rms < 100:
            raise ValueError('Bad voice duration/silence')
        if peak >= .98:
            high_peaks.append(stem)
        shutil.copyfile(source, dataset / source.name)
        durations.append(duration)
        details[stem] = {'text': text, 'duration_seconds': duration, 'rms': rms, 'peak_ratio': peak,
                         'source_ids': source_ids[(stem, text)]}
        lines.append(f'dataset/{slug}/{stem}.wav|{slug}|ja|{text}')
    (folder / 'labels').mkdir()
    (folder / 'labels' / (slug + '.list')).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    reference = folder / 'reference'
    reference.mkdir()
    refs = []
    for number, stem in enumerate(REFERENCES[slug], 1):
        item = details[stem]
        if not (5 <= item['duration_seconds'] <= 10 and item['rms'] >= 800 and item['peak_ratio'] < .98):
            raise ValueError('Bad daily voice reference')
        wav = reference / f'{slug}_ref_{number}.wav'
        shutil.copyfile(dataset / (stem + '.wav'), wav)
        wav.with_suffix('.txt').write_text(item['text'], encoding='utf-8')
        refs.append(dict(item, voice_id=stem, file=wav.relative_to(folder).as_posix()))
    json_file(reference / 'provenance.json', refs)
    jsonl_file(folder / 'provenance/labels.jsonl', [dict(details[stem], voice_id=stem) for stem, _ in selected])
    summary = {'original_annotation_rows': len(labels), 'training_labels': len(selected),
               'duration_seconds': round(sum(durations), 3), 'duration_hours': round(sum(durations) / 3600, 3),
               'excluded_from_original_labels': excluded, 'high_peak_audio_ids': high_peaks,
               'audio_format': '32000 Hz / mono / signed 16-bit PCM', 'references': 3,
               'references_text_reviewed': True, 'audio_manually_listened': False,
               'original_datasets_modified': False, 'models_trained': False}
    json_file(folder / 'qa.json', summary)
    (folder / 'README_先读我.md').write_text(f'''# {CHARACTERS[slug]}（{slug}）语音训练交接包

内含 {len(selected)} 个 WAV 与一一对应标注，合计 {summary['duration_hours']} 小时。
音频为 32 kHz、单声道、16-bit PCM，标注语种 `ja`。数据已准备，模型未训练，音色未克隆。
只装入原标注中能与本次保守文本来源匹配、时长 2–15 秒的片段；未改原项目数据。
旧参考仅按音量挑选，可能混入喘息；本包三组参考已从完整日常台词重选。
参考文本已审阅、音频格式和响度已测量，尚未逐条人工试听。高峰值列表见 qa.json（不等同于确认削波）。

## 训练前执行

1. 在上传后的机器解压整包，进入包含 handoff.py 的目录。Python 3.10+，无需额外库。
2. `python handoff.py verify`：检查文件 SHA256、格式、时长、标注唯一性。
3. `python handoff.py paths`：按当前解压位置生成绝对路径 `train.list`，原 labels/{slug}.list 不变。
   若数据另放别处，用 `python handoff.py paths --dataset-root /你的路径/dataset`。
   请在最终训练机器上运行，不能把本机 D: 路径带去 Linux。
4. GPT-SoVITS 的训练标注填 train.list 的绝对路径，语种选日文/ja，角色单独训练。
5. reference/ 的三组 WAV/TXT 用于推理参考（ja），中文输出需用你安装版本支持的跨语言推理。
   训练版本/基座/超参数按实际环境配置；数据质检不代表音色、中文效果已经验收。

原始 labels 用相对路径，不需要 sed 字符串替换；handoff.py 会验证每个目标音频存在。
dataset/ 只有实际参加训练的 WAV，不夹带时长越界文件；不重复标注、不混入其他角色声音。
provenance/labels.jsonl 与 reference/provenance.json 保留源台词 ID 和参考文本。
manifest.json 为全包逐文件 SHA256。包内无密钥、数据库、用户聊天、游戏程序或模型权重。
''', encoding='utf-8')
    return summary


def verify_zip(archive, destination):
    with ZipFile(archive) as z:
        bad = z.testzip()
        if bad:
            raise ValueError('ZIP CRC mismatch')
        names = z.namelist()
        if len(set(names)) != len(names) or any(n.startswith('/') or '..' in Path(n).parts or '\\' in n for n in names):
            raise ValueError('Unsafe ZIP entries')
        prefix = names[0].split('/')[0] + '/'
        metadata = json.loads(z.read(prefix + 'manifest.json'))
        expected = {prefix + name for name in metadata['files']} | {prefix + 'manifest.json'}
        if set(names) != expected:
            raise ValueError('ZIP manifest coverage mismatch')
        for relative, item in metadata['files'].items():
            data = z.read(prefix + relative)
            if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('ZIP file checksum mismatch')
        z.extractall(destination)
    folder = destination / prefix.rstrip('/')
    r = subprocess.run([sys.executable, str(folder / 'handoff.py'), 'verify'], cwd=destination, capture_output=True, text=True, encoding='utf-8')
    if r.returncode:
        raise ValueError('Extracted package verification failed: ' + r.stderr[-1000:])
    package = json.loads((folder / 'package.json').read_text(encoding='utf-8'))
    command = ['paths'] if package['kind'] == 'voice' else ['convert']
    r = subprocess.run([sys.executable, str(folder / 'handoff.py'), *command], cwd=destination, capture_output=True, text=True, encoding='utf-8')
    if r.returncode:
        raise ValueError('Extracted portable command failed: ' + r.stderr[-1000:])
    return {'zip_crc': 'passed', 'all_member_sha256': 'passed', 'extracted_verifier': 'passed',
            'portable_command': ' '.join(command), 'portable_command_result': 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stamp', default=datetime.now().strftime('%Y%m%d_%H%M%S'))
    args = parser.parse_args()
    if not args.stamp.replace('_', '').isdigit():
        parser.error('stamp must contain digits/underscores only')
    staging = ROOT / 'share/training-handoff' / args.stamp
    staging.mkdir(parents=True, exist_ok=False)
    rows = read_rows(ROOT / 'backend/story_data/records.jsonl')
    examples = read_rows(ROOT / 'backend/story_data/dialogue_examples.jsonl')
    tts = load_module('tts_builder', ROOT / 'finetune_data/tts/build_dataset.py')
    archives = []
    for slug, name in CHARACTERS.items():
        sources = select_sources(rows, examples, slug)
        legacy = read_rows(ROOT / 'extracted/characters' / slug / 'lines_clean.jsonl')
        for kind, label in [('text', '文本'), ('voice', '语音')]:
            folder = staging / f'AIlover_{slug}_{kind}'
            summary = text_package(folder, slug, sources, legacy) if kind == 'text' else voice_package(folder, slug, sources, tts)
            manifest(folder)
            output = ROOT / f'AIlover_{name}_{label}训练交接包_{args.stamp}.zip'
            with ZipFile(output, 'x', compression=ZIP_DEFLATED, compresslevel=6) as z:
                for path in sorted(folder.rglob('*')):
                    if path.is_file():
                        z.write(path, path.relative_to(staging).as_posix())
            checks = verify_zip(output, staging / 'extracted-checks' / f'{slug}-{kind}')
            archives.append({'slug': slug, 'name': name, 'kind': kind, 'file': output.name,
                             'bytes': output.stat().st_size, 'sha256': digest(output), 'summary': summary, 'checks': checks})
            print(f'Checked {output.name}: {output.stat().st_size / 1024 / 1024:.2f} MiB', flush=True)
    json_file(ROOT / f'AIlover_训练交接包校验_{args.stamp}.json', {'archives': archives, 'external_api_calls': 0})
    overview = '# 三位角色训练交接包\n\n每位角色分文本、语音两个 ZIP，均位于 AIlover 根目录。\n\n|角色|包|文件|内容|\n|---|---|---|---|\n'
    for a in archives:
        count = (f"日文来源 {a['summary']['source_records']} + 中文改写 seed 5" if a['kind'] == 'text'
                 else f"WAV/标注 {a['summary']['training_labels']}，{a['summary']['duration_hours']} 小时，参考3组")
        overview += f"|{a['name']}|{'文本' if a['kind']=='text' else '语音'}|[{a['file']}]({a['file']})|{count}|\n"
    overview += '\n每个 ZIP 已检查 CRC、逐文件 SHA256，并实际解压到另一目录运行内置校验和离线命令。\n'
    overview += '\n文本包的完整中文语料尚未翻译，模型尚未训练；5条 seed 不能冒充全量训练集。语音包可用于下一步训练准备，音色效果仍需训练后试听。\n'
    overview += '\n包内有独立 README_先读我.md、handoff.py、manifest.json。文本包可独立续跑真实翻译/转换；语音包可在最终训练机器自动生成 train.list。原材料保持不变，无密钥、用户数据库或聊天。\n'
    (ROOT / f'AIlover_训练交接包_先看这里_{args.stamp}.md').write_text(overview, encoding='utf-8')


if __name__ == '__main__':
    main()
