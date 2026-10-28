"""Build Chinese Hotaru runtime evidence from exact CMVS JA/ZH associations.

Original binary locations and Japanese labels remain available. Runtime style
contexts contain only safe preceding records, never the target or future text.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from hotaru_training_common import context_error, context_rows, rows_read, rows_write, sha, json_write

ROOT = Path(__file__).resolve().parents[1]


def normalize(row, voices):
    voice = voices.get(row.get('voice_id'))
    speaker = row.get('zh_speaker_raw') or ('旁白' if row.get('evidence_type') == 'narration' else row.get('speaker'))
    return dict(row, text=row['zh_text'], raw_text=row['zh_raw_text'], text_language='zh',
                speaker=speaker, original_speaker=row.get('speaker'),
                source_game='amatsutsumi', source_sha256=row['zh_source_sha256'],
                source_location={key: row.get(key) for key in
                    ('message_id', 'speaker_index', 'ja_opcode_offset', 'zh_opcode_offset', 'ja_string_offset', 'zh_string_offset')},
                source_location_kind='CMVS_PS3_binary_offsets_not_text_lines',
                audio_path=str(ROOT / voice['path']) if voice else None,
                audio_language='ja' if voice else None,
                audio_sha256=voice['sha256'] if voice else None,
                context=[], uncertainties=['automatic_scene_screen_not_human_review'], reviewed=False)


def build_sources(ledger, inventory, output):
    ledger, inventory, output = map(Path, (ledger, inventory, output))
    if any((output / name).exists() for name in ('source_records.jsonl', 'dialogue_examples.jsonl', 'lines_clean.jsonl')):
        raise ValueError('Refusing to overwrite an existing Hotaru runtime source build')
    rows = rows_read(ledger)
    voices = {row['voice_id']: row for row in rows_read(inventory)}
    # Every mapped audio remains the archive-verified original, without relabeling it Chinese.
    for voice in voices.values():
        if sha(ROOT / voice['path']) != voice['sha256']:
            raise ValueError('Original Hotaru voice changed: ' + voice['voice_id'])
    raw, examples, excluded, legacy = [], [], [], []
    for index, row in enumerate(rows):
        if row.get('character') != 'hotaru':
            continue
        record = normalize(row, voices)
        raw.append(record)
        previous = context_rows(rows, index)
        reason = context_error(row, previous)
        if reason:
            excluded.append(dict(source_id=row['id'], reason=reason, source_file=row['source_file'],
                                 source_location=record['source_location'], scene_safety=row.get('scene_safety')))
            continue
        context = [dict(id=item['id'], speaker=item.get('zh_speaker_raw') or ('旁白' if item.get('evidence_type') == 'narration' else item['speaker']), text=item['zh_text'],
                        evidence_type=item['evidence_type'], text_language='zh',
                        source_file=item['source_file'], segment=item.get('segment'),
                        sequence=item['sequence'], source_sha256=item['zh_source_sha256']) for item in previous]
        if any(item['id'] == record['id'] or item['sequence'] >= record['sequence']
               or item['source_file'] != record['source_file'] or item['segment'] != record.get('segment') for item in context):
            raise ValueError('Runtime context crossed target/future/source boundaries')
        examples.append(dict(record, evidence_type='style', style_labels=[], context=context,
                             context_policy='only 2-6 safe preceding rows in same verified linear block'))
        legacy.append(dict(text=record['text'], ja_text=record['ja_text'], voice=record['audio_path'],
                           file=record['source_file'], source_id=record['id'], source_sha256=record['source_sha256'],
                           text_language='zh', translation_source=record['translation_source']))
    if not examples:
        raise ValueError('No safe source-grounded Hotaru runtime style examples')
    output.mkdir(parents=True, exist_ok=True)
    for name, values in (('source_records', raw), ('dialogue_examples', examples), ('lines_clean', legacy), ('runtime_excluded', excluded)):
        rows_write(output / (name + '.jsonl'), values)
    report = dict(character='hotaru', raw_source_records=len(raw), safe_style_examples=len(examples),
                  excluded=len(excluded), exclusion_reasons=dict(Counter(row['reason'] for row in excluded)),
                  source_ledger_sha256=sha(ledger), voice_inventory_sha256=sha(inventory),
                  text_language='zh', audio_language='ja', human_reviewed=False,
                  context_target_future_leak=False, scene_screening='automatic_not_human_certification')
    json_write(output / 'runtime_source_report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, default=ROOT / 'extracted/amatsutsumi/source/aligned_records.jsonl')
    parser.add_argument('--voice-inventory', type=Path, default=ROOT / 'extracted/amatsutsumi/source/hotaru_voice_inventory.jsonl')
    parser.add_argument('--output', type=Path, default=ROOT / 'extracted/characters/hotaru')
    args = parser.parse_args()
    print(json.dumps(build_sources(args.ledger, args.voice_inventory, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
