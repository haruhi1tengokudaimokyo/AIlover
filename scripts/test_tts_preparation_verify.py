"""Integrity regressions using synthetic PCM/KS only; no game data or model calls."""
from collections import defaultdict
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave

import tts_preparation_verify as verifier


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def refresh_manifest(root):
    write_json(root / 'manifest.json', {'files': {
        path.relative_to(root).as_posix(): {'bytes': path.stat().st_size, 'sha256': verifier.digest(path)}
        for path in root.rglob('*') if path.is_file() and path.name != 'manifest.json'}})


def build_fixture(root, multiple_zh=False):
    root.mkdir()
    source_files = {'shared.ks': [1, 2] + ([1] if multiple_zh else []),
                    'validation.ks': [3], 'test.ks': [4]}
    ledger = []
    for filename, voices in source_files.items():
        for lang, speaker in [('ja', 'むぎ'), ('zh', '麦')]:
            source = '*Start\n'
            for ordinal, number in enumerate(voices):
                text = ('こんにちは' if lang == 'ja' else '你好') + str(number)
                if lang == 'zh' and multiple_zh and ordinal == 2:
                    text = '另一种译文'
                source += f'[{speaker} vo=vo1_{number:04d}]\n[>>]{text}[<<][c]\n'
            path = root / 'source' / lang / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding='utf-8')
        ja_path, zh_path = root / 'source/ja' / filename, root / 'source/zh' / filename
        ja = verifier.parse_source(ja_path, filename)
        zh = verifier.parse_source(zh_path, filename)
        for ident, row in ja.items():
            ledger.append({'source_line_id': ident, 'voice_id': row['voice_id'], 'character': 'mugi',
                'ja_text': row['text'], 'zh_text': zh[ident]['text'], 'source_file': filename,
                'source_location': row['source_location'], 'source_scene_id': row['source_scene_id'],
                'ja_script_sha256': verifier.digest(ja_path), 'zh_script_sha256': verifier.digest(zh_path),
                'ja_speaker': row['speaker'], 'zh_speaker': zh[ident]['speaker']})
    by_voice = defaultdict(list)
    for occurrence in ledger:
        by_voice[occurrence['voice_id']].append(occurrence)
    raw, accepted, cross, targets = [], [], [], []
    for number, split in enumerate(('train', 'reference', 'validation', 'test'), 1):
        voice = f'vo1_{number:04d}'
        occurrences = by_voice[voice]
        relative = f'tts_adaptation/mugi/audio/mugi_{voice}.wav'
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), 'wb') as audio:
            audio.setparams((1, 2, 32000, 0, 'NONE', 'not compressed'))
            audio.writeframes(struct.pack('<h', number * 100) * 8000)
        variants = sorted({o['zh_text'] for o in occurrences})
        base = {'utterance_id': 'mugi_' + voice, 'character_id': 'mugi',
            'audio_path': 'external/native/' + voice + '.opus', 'audio_path_scope': 'external',
            'ja_text': occurrences[0]['ja_text'], 'zh_text': variants[0] if len(variants) == 1 else None,
            'source_game_file': occurrences[0]['source_file'],
            'source_scene_id': occurrences[0]['source_scene_id'] if len(occurrences) == 1 else None,
            'source_line_id': occurrences[0]['source_line_id'], 'audio_start': 0, 'audio_end': .25,
            'audio_language': 'ja', 'alignment_status': 'synthetic_fixture_aligned',
            'quality_status': 'synthetic_fixture_only', 'review_status': 'not_listened',
            'speaker_confidence': 'synthetic_fixture', 'transcript_confidence': 'synthetic_fixture',
            'source_occurrences': occurrences}
        raw.append(base)
        info = verifier.wav_info(path)
        accepted.append(dict(base, audio_path=relative, audio_path_scope='package', split=split,
                             partition_group=occurrences[0]['source_file'],
                             partition_group_split='train' if split == 'reference' else split,
                             **{k: value for k, value in info.items() if k != 'frames'}))
        cross.append({'utterance_id': base['utterance_id'], 'zh_text': base['zh_text'],
            'zh_variants': [{'zh_text': text, 'source_line_ids': [o['source_line_id'] for o in occurrences if o['zh_text'] == text]}
                            for text in variants]})
        targets.extend({'utterance_id': base['utterance_id'], 'source_line_id': o['source_line_id'],
                        'zh_text': o['zh_text']} for o in occurrences)
    bonus = dict(raw[0], utterance_id='mugi_bonus_no_transcript', audio_path='external/bonus.opus',
                 ja_text=None, zh_text=None, source_line_id=None, source_game_file=None,
                 source_scene_id=None, source_occurrences=[], alignment_status='missing_script',
                 quality_reasons=['missing_script'])
    raw.append(bonus)
    write_json(root / 'package.json', {'characters': ['mugi']})
    write_json(root / 'zh_supervised_data_status.json', {'actual_chinese_recordings': 0, 'valid_zh_audio_text_pairs': 0})
    write_rows(root / 'source/occurrences.jsonl', ledger)
    write_rows(root / 'alignment/index.jsonl', raw)
    write_rows(root / 'tts_adaptation/mugi/accepted.jsonl', accepted)
    write_rows(root / 'tts_adaptation/mugi/excluded.jsonl', [bonus])
    write_rows(root / 'crosslingual_alignment/mugi.jsonl', cross)
    write_rows(root / 'zh_target_text/mugi.jsonl', targets)
    write_json(root / 'references/mugi.json', [{key: row[key] for key in ('utterance_id', 'audio_path', 'ja_text')}
                                             for row in accepted if row['split'] == 'reference'])
    for name in verifier.LISTS:
        selected = accepted if name == 'all' else [row for row in accepted if row['split'] == ('train' if name == 'fewshot_15min' else name)]
        path = root / 'tts_adaptation/mugi/labels' / (name + '.list')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(f"{r['audio_path']}|mugi|ja|{verifier.clean_ja(r['ja_text'])}\n" for r in selected), encoding='utf-8')
    refresh_manifest(root)
    return accepted


class TtsPreparationVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='tts-verifier-regression-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'package'
        self.accepted = build_fixture(self.root)

    def test_valid_package_reads_all_audio_and_partitions_raw_bonus(self):
        result = verifier.verify(self.root)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['counts']['mugi']['raw_utterances'], 5)
        self.assertEqual(result['counts']['mugi']['accepted'], 4)
        self.assertEqual(result['counts']['mugi']['excluded'], 1)
        self.assertEqual(result['actual_chinese_recordings'], 0)

    def test_visual_icon_only_line_has_no_invented_japanese_transcript(self):
        filename = 'icon_only.ks'
        for lang, speaker, text in [('ja', 'むぎ', '[icHeart]'), ('zh', '麦', '啊')]:
            path = self.root / 'source' / lang / filename
            path.write_text(f'*Start\n[{speaker} vo=vo1_0005]\n[>>]{text}[<<][c]\n', encoding='utf-8')
        ja_path, zh_path = self.root / 'source/ja' / filename, self.root / 'source/zh' / filename
        ja = next(iter(verifier.parse_source(ja_path, filename).values()))
        zh = next(iter(verifier.parse_source(zh_path, filename).values()))
        occurrence = {'source_line_id': ja['source_line_id'], 'voice_id': ja['voice_id'], 'character': 'mugi',
            'ja_text': '', 'zh_text': '啊', 'source_file': filename, 'source_location': ja['source_location'],
            'source_scene_id': ja['source_scene_id'], 'ja_script_sha256': verifier.digest(ja_path),
            'zh_script_sha256': verifier.digest(zh_path), 'ja_speaker': ja['speaker'], 'zh_speaker': zh['speaker']}
        ledger_path = self.root / 'source/occurrences.jsonl'
        write_rows(ledger_path, verifier.jsonl_read(ledger_path) + [occurrence])
        index_path = self.root / 'alignment/index.jsonl'
        old = verifier.jsonl_read(index_path)
        row = dict(old[-1], utterance_id='mugi_empty_spoken_text', ja_text=None, zh_text='啊',
                   source_game_file=filename, source_scene_id=ja['source_scene_id'], source_line_id=ja['source_line_id'],
                   source_occurrences=[occurrence], quality_reasons=['missing_spoken_transcript'])
        write_rows(index_path, old + [row])
        ex = self.root / 'tts_adaptation/mugi/excluded.jsonl'
        write_rows(ex, verifier.jsonl_read(ex) + [row])
        refresh_manifest(self.root)
        result = verifier.verify(self.root)
        self.assertEqual(result['counts']['mugi']['excluded'], 2)

    def test_localized_scene_label_is_preserved_as_explicit_mapping(self):
        path = self.root / 'source/zh/shared.ks'
        path.write_text(path.read_text(encoding='utf-8').replace('*Start', '*开始'), encoding='utf-8')
        new_sha = verifier.digest(path)
        ledger_path = self.root / 'source/occurrences.jsonl'
        ledger = verifier.jsonl_read(ledger_path)
        mapping = []
        for row in ledger:
            if row['source_file'] == 'shared.ks':
                row['zh_script_sha256'] = new_sha
                mapping.append({'source_line_id': row['source_line_id'], 'character': 'mugi',
                                'ja_source_scene_id': 'shared.ks#Start', 'zh_source_scene_id': 'shared.ks#开始'})
        write_rows(ledger_path, ledger)
        for relative in ('alignment/index.jsonl', 'tts_adaptation/mugi/accepted.jsonl'):
            rows = verifier.jsonl_read(self.root / relative)
            for row in rows:
                for source in row['source_occurrences']:
                    if source['source_file'] == 'shared.ks':
                        source['zh_script_sha256'] = new_sha
            write_rows(self.root / relative, rows)
        write_rows(self.root / 'source/scene_label_variants.jsonl', mapping)
        refresh_manifest(self.root)
        self.assertEqual(verifier.verify(self.root)['status'], 'passed')

    def test_chinese_label_replacement_rejected_after_rehash(self):
        path = self.root / 'tts_adaptation/mugi/labels/train.list'
        path.write_text(path.read_text(encoding='utf-8').replace('こんにちは1', '你好'), encoding='utf-8')
        refresh_manifest(self.root)
        with self.assertRaisesRegex(ValueError, 'Labels differ'):
            verifier.verify(self.root)

    def test_missing_wav_rejected_after_manifest_refresh(self):
        (self.root / self.accepted[0]['audio_path']).unlink()
        refresh_manifest(self.root)
        with self.assertRaises(OSError):
            verifier.verify(self.root)

    def test_truncated_wav_not_just_header_checked(self):
        path = self.root / self.accepted[0]['audio_path']
        path.write_bytes(path.read_bytes()[:-64])
        refresh_manifest(self.root)
        with self.assertRaisesRegex(ValueError, 'frame count'):
            verifier.verify(self.root)

    def test_repartition_same_source_file_rejected(self):
        self.accepted[1]['split'] = self.accepted[1]['partition_group_split'] = 'validation'
        write_rows(self.root / 'tts_adaptation/mugi/accepted.jsonl', self.accepted)
        refresh_manifest(self.root)
        with self.assertRaisesRegex(ValueError, 'group leaks'):
            verifier.verify(self.root)

    def test_identical_pcm_rejected_even_when_hash_metadata_updated(self):
        first, second = self.root / self.accepted[0]['audio_path'], self.root / self.accepted[2]['audio_path']
        second.write_bytes(first.read_bytes())
        self.accepted[2].update({k: value for k, value in verifier.wav_info(second).items() if k != 'frames'})
        write_rows(self.root / 'tts_adaptation/mugi/accepted.jsonl', self.accepted)
        refresh_manifest(self.root)
        with self.assertRaisesRegex(ValueError, 'Duplicate accepted PCM'):
            verifier.verify(self.root)

    def test_multiple_chinese_variants_preserved_and_collapse_rejected(self):
        other = Path(self.temporary.name) / 'variants'
        build_fixture(other, multiple_zh=True)
        self.assertEqual(verifier.verify(other)['status'], 'passed')
        path = other / 'crosslingual_alignment/mugi.jsonl'
        rows = verifier.jsonl_read(path)
        rows[0]['zh_text'] = rows[0]['zh_variants'][0]['zh_text']
        write_rows(path, rows)
        refresh_manifest(other)
        with self.assertRaisesRegex(ValueError, 'variants were silently collapsed'):
            verifier.verify(other)

    def test_source_text_fabrication_rejected_even_after_rehash(self):
        path = self.root / 'source/occurrences.jsonl'
        rows = verifier.jsonl_read(path)
        rows[0]['ja_text'] = 'invented transcript'
        write_rows(path, rows)
        refresh_manifest(self.root)
        with self.assertRaisesRegex(ValueError, 'Source transcript'):
            verifier.verify(self.root)

    def test_paths_outside_package_and_never_modify_controlled_inputs(self):
        before = {p: verifier.digest(p) for p in self.root.rglob('*') if p.is_file()}
        output = Path(self.temporary.name) / 'absolute_paths'
        result = verifier.absolute_paths(self.root, 'mugi', output)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(before, {p: verifier.digest(p) for p in self.root.rglob('*') if p.is_file()})
        for filename in result['output_files']:
            for line in Path(filename).read_text(encoding='utf-8').splitlines():
                self.assertTrue(Path(line.split('|')[0]).is_absolute())
        with self.assertRaisesRegex(ValueError, 'outside the manifest'):
            verifier.absolute_paths(self.root, 'mugi', self.root / 'generated')

    def test_fewshot_cannot_take_reference_audio(self):
        reference = self.accepted[1]
        path = self.root / 'tts_adaptation/mugi/labels/fewshot_15min.list'
        path.write_text(f"{reference['audio_path']}|mugi|ja|{reference['ja_text']}\n", encoding='utf-8')
        refresh_manifest(self.root)
        with self.assertRaisesRegex(ValueError, 'Few-shot labels include non-training'):
            verifier.verify(self.root)


if __name__ == '__main__':
    unittest.main()
