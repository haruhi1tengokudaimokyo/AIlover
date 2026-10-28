"""Create parity reference/stats/glossary files from the finished source pipeline."""
from collections import Counter
from pathlib import Path
import shutil
from hotaru_training_common import json_read, json_write, rows_read, rows_write, sha

ROOT = Path(__file__).resolve().parents[1]


def main():
    extracted = ROOT / 'extracted/characters/hotaru'
    data = ROOT / 'finetune_data/hotaru'
    build = data / 'preparation-v1'
    ledger = rows_read(ROOT / 'extracted/amatsutsumi/source/aligned_records.jsonl')
    mine = [r for r in ledger if r['character'] == 'hotaru']
    voices = {r['voice_id']: r for r in rows_read(ROOT / 'extracted/amatsutsumi/source/hotaru_voice_inventory.jsonl')}
    records = rows_read(extracted / 'source_records.jsonl')
    styles = rows_read(extracted / 'dialogue_examples.jsonl')
    rows_write(extracted / 'source_corpus.jsonl', [dict(r, char=r['speaker'], text=r['ja_text'], voice=r['voice_id'], file=r['source_file']) for r in mine])
    rows_write(data / 'llm/source/dialogue_examples.jsonl', styles)
    rows_write(data / 'llm/source/aligned_originals.jsonl', records)
    canonical = build / 'AIlover_Hotaru_Text_V3'
    target = data / 'llm/output'
    target.mkdir(parents=True, exist_ok=True)
    for split in ('train', 'validation', 'test'):
        shutil.copyfile(canonical / f'sft/canonical_context_only/{split}.json', target / (split + '.json'))
    shutil.copyfile(canonical / 'sft/dataset_info.json', target / 'package_dataset_info_reference.json')
    json_write(target / 'dataset_info.json', {f'hotaru_{s}': {'file_name': s + '.json', 'formatting': 'sharegpt',
        'columns': {'messages': 'conversations', 'system': 'system'},
        'tags': {'role_tag': 'from', 'content_tag': 'value', 'user_tag': 'human', 'assistant_tag': 'gpt'}}
        for s in ('train', 'validation', 'test')})
    aliases = Counter((r['speaker'].replace('\u3000', ''), (r.get('zh_speaker_raw') or '').replace('\u3000', ''))
        for r in ledger if r['speaker'] and r.get('zh_speaker_raw') and not r.get('localized_speaker_conflict'))
    glossary = [{'ja': ja, 'zh': zh, 'source_occurrences': count, 'basis': 'actual JA/ZH PS3 speaker labels, not machine translation'}
        for (ja, zh), count in aliases.most_common()]
    json_write(data / 'glossary.json', glossary)
    references = json_read(build / 'AIlover_Hotaru_TTS_Preparation_V1/references/hotaru.json')
    if not references:
        raise ValueError('No actual reference candidates')
    first = references[0]
    audio_record = next(r for r in rows_read(build / 'AIlover_Hotaru_TTS_Preparation_V1/alignment/index.jsonl') if r['utterance_id'] == first['utterance_id'])
    native = voices[audio_record['voice_id']]
    asset_dir = ROOT / 'backend/seed_assets/hotaru'
    asset_dir.mkdir(parents=True, exist_ok=True)
    source = ROOT / native['path']
    destination = asset_dir / ('voice_ref' + source.suffix)
    if destination.exists() and sha(destination) != native['sha256']:
        raise ValueError('Refusing to overwrite a different original voice reference')
    shutil.copyfile(source, destination)
    (asset_dir / 'voice_ref.txt').write_text(first['ja_text'] + '\n', encoding='utf-8')
    json_write(asset_dir / 'voice_ref.provenance.json', dict(native, **first, actual_audio_language='ja',
        generated_voice=False, chinese_recording=False, listening_certified=False, reference_sha256=sha(destination)))
    analyses = {r['voice_id']: r for r in rows_read(build / 'analysis/audio.jsonl')}
    safe_ids = {r['id'] for r in styles}
    candidates = [r for r in mine if r['id'] in safe_ids and r['voice_id'] in analyses and
        analyses[r['voice_id']]['metrics'] and 5 <= analyses[r['voice_id']]['metrics']['duration_seconds'] <= 10]
    rows_write(extracted / 'ref_candidates.jsonl', [dict(r, audio=voices[r['voice_id']], review_status='candidate_pending_listening') for r in candidates[:60]])
    (extracted / 'ref_candidates.txt').write_text('\n'.join(f"{r['voice_id']}|ja|{r['ja_text']}" for r in candidates[:60]) + '\n', encoding='utf-8')
    sample = styles[::max(1, len(styles) // 120)][:120]
    (extracted / 'sample_lines.txt').write_text('\n'.join(f"{r['id']}\nZH: {r['text']}\nJA: {r['ja_text']}\n来源: {r['source_file']} {r['source_location']}\n" for r in sample), encoding='utf-8')
    japanese = '\n'.join(r['ja_text'] for r in mine)
    terms = ['私', 'わたし', 'あたし', '誠', '誠くん', 'あなた', '君', 'こころ', '愛', '響子']
    stats = {'source_records': len(mine), 'safe_runtime_examples': len(styles), 'source_files': len({r['source_file'] for r in mine}),
        'term_occurrences_not_exclusive_counts': {term: japanese.count(term) for term in terms}, 'reference_candidates': min(60, len(candidates)),
        'sampled_lines': len(sample), 'automatic_filtering_only': True}
    json_write(extracted / 'stats.json', stats)
    (extracted / 'stats.txt').write_text('\n'.join(f'{key}: {value}' for key, value in stats.items()) + '\n', encoding='utf-8')
    (data / 'README.md').write_text('''# 水无月萤微调交接材料

首层交付：AIlover_Hotaru_Text_V3.zip（中文文本）与AIlover_Hotaru_TTS_Preparation_V1.zip（日语原声）。
preparation-v1/verified_delivery是实际重新解压通过的交付内容；音频只在语音包与其必要工作缓存中，不再复制一套legacy dataset。
llm/source保留真实来源与前序中文情境，ja_text另存；llm/output提供可用中文ShareGPT及本目录dataset_info.json。
glossary.json来自真实双语说话人标签。原始资料、语音均在extracted/amatsutsumi，角色抽样、统计和参考候选在extracted/characters/hotaru。
backend/seed_assets/hotaru/voice_ref.ogg是原始日语参考，未冒充中文配音或已适配声音。
本轮未训练、未推理、未调用外部生成API。最终数据数字与SHA256以根报告和校验JSON为准。
''', encoding='utf-8')
    print('Hotaru parity references/statistics/LLM handoff files created; original Japanese reference preserved.')


if __name__ == '__main__':
    main()
