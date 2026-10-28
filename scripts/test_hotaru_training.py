"""Source/context/voice-label regression tests; fixtures are synthetic, not game data."""
import copy
from pathlib import Path
import tempfile
import unittest

from build_hotaru_training import allocate, canonical_samples, voice_index
from hotaru_training_common import context_error, context_rows, safe_path
from hotaru_training_common import japanese_label


def fixture_rows():
    return [dict(id=f'amatsutsumi_fixture_{i}', source_file='test.ps3', scene_id='test.ps3#0',
        segment=0, sequence=i, speaker=speaker, character=character, voice_id=f'fixture_{i}',
        ja_text=ja, zh_text=zh, alignment_status='confirmed', evidence_type='dialogue', scene_safety='normal')
        for i, (speaker, character, ja, zh) in enumerate([
            ('诚', 'makoto', '今日はいい天気だね。', '今天的天气真不错。'),
            ('萤', 'hotaru', '外に行こうか。', '那要不要出去走一走？'),
            ('诚', 'makoto', 'どこに行きたい？', '你有没有想去看看的地方？'),
            ('萤', 'hotaru', '海を見に行こう。', '一起去看看海吧，慢慢走过去也好。')])]


class ContextTests(unittest.TestCase):
    def test_actual_preceding_context_without_future(self):
        rows = fixture_rows()
        kept, _, _ = canonical_samples(rows, '中文人物设定', {'test.ps3': 'train'})
        self.assertEqual(len(kept), 1)
        sample = kept[0]
        self.assertEqual(sample['context_ids'], [r['id'] for r in rows[:3]])
        self.assertNotIn(rows[3]['zh_text'], sample['sample']['conversations'][0]['value'])
        self.assertEqual(sample['sample']['conversations'][-1]['value'], rows[3]['zh_text'])
        self.assertIn('诚', sample['sample']['conversations'][0]['value'])

    def test_context_does_not_cross_scene(self):
        rows = fixture_rows()
        rows[3]['scene_id'] = 'new_scene'
        self.assertEqual(context_rows(rows, 3), [])
        self.assertEqual(context_error(rows[3], []), 'insufficient_preceding_context')

    def test_private_narration_is_quarantined(self):
        rows = fixture_rows()
        rows[0].update(evidence_type='narration', zh_text='我心想她一定还在隐瞒什么。')
        self.assertEqual(context_error(rows[3], rows[:3]), 'private_narration')

    def test_unconfirmed_or_unresolved_branch_not_accepted(self):
        rows = fixture_rows()
        rows[3]['alignment_status'] = 'pending'
        self.assertEqual(context_error(rows[3], rows[:3]), 'alignment_unconfirmed')
        rows[3].update(alignment_status='confirmed', branch_uncertain=True)
        self.assertEqual(context_error(rows[3], rows[:3]), 'unresolved_scene_or_branch')

    def test_target_already_present_rejected(self):
        rows = fixture_rows()
        rows[0]['zh_text'] = rows[3]['zh_text']
        self.assertEqual(context_error(rows[3], rows[:3]), 'target_already_in_input')

    def test_source_files_indivisible_with_real_holdouts(self):
        rows = [dict(source_file=f'{i}.ps3') for i in range(10)]
        result = allocate(rows + rows)
        self.assertEqual(len(result), 10)
        self.assertEqual(set(result.values()), {'train', 'validation', 'test'})
        self.assertEqual(result, allocate(rows))


class VoiceTests(unittest.TestCase):
    def audio(self):
        return {'voice_id': 'fixture_3', 'source': {'path': 'test.ogg', 'sha256': 'a' * 64}, 'decode_error': None,
            'metrics': {'duration_seconds': 5, 'pcm_sha256': 'b' * 64, 'rms': 1000,
                'active_frame_ratio': 1, 'clipped_sample_ratio': 0, 'start_10ms_rms': 0,
                'end_10ms_rms': 0, 'start_sample_ratio': 0, 'end_sample_ratio': 0,
                'leading_silence_seconds': 0, 'trailing_silence_seconds': 0, 'peak_ratio': .5}}

    def test_japanese_audio_keeps_japanese_label_and_chinese_separate(self):
        rows = fixture_rows()
        result = voice_index([self.audio()], rows, {'test.ps3': 'train'})[0]
        self.assertFalse(result['quality_reasons'])
        self.assertEqual(result['audio_language'], 'ja')
        self.assertEqual(result['ja_text'], rows[3]['ja_text'])
        self.assertEqual(result['zh_variants'][0]['zh_text'], rows[3]['zh_text'])

    def test_conflicting_transcript_quarantined(self):
        rows = fixture_rows()
        other = copy.deepcopy(rows[-1])
        other.update(id='different_source', ja_text='別の台詞です。')
        result = voice_index([self.audio()], rows + [other], {'test.ps3': 'train'})[0]
        self.assertIsNone(result['ja_text'])
        self.assertIn('missing_or_conflicting_japanese_transcript', result['quality_reasons'])

    def test_same_voice_across_partitions_quarantined(self):
        rows = fixture_rows()
        other = copy.deepcopy(rows[-1])
        other.update(id='other_scene', source_file='other.ps3')
        result = voice_index([self.audio()], rows + [other], {'test.ps3': 'train', 'other.ps3': 'test'})[0]
        self.assertIn('reused_voice_crosses_source_partitions', result['quality_reasons'])

    def test_chinese_translation_variants_are_preserved(self):
        rows = fixture_rows()
        other = copy.deepcopy(rows[-1])
        other.update(id='other_translation', zh_text='我们去海边看看，散散步就好。')
        result = voice_index([self.audio()], rows + [other], {'test.ps3': 'train'})[0]
        self.assertFalse(result['quality_reasons'])
        self.assertIsNone(result['zh_text'])
        self.assertEqual(len(result['zh_variants']), 2)

    def test_masked_speaker_script_remains_traceable_but_excluded(self):
        rows = fixture_rows()
        rows[-1].update(speaker='？？？', character='？？？')
        result = voice_index([self.audio()], rows, {'test.ps3': 'train'})[0]
        self.assertEqual(result['ja_text'], rows[-1]['ja_text'])
        self.assertEqual(result['source_line_ids'], [rows[-1]['id']])
        self.assertIn('script_display_speaker_unconfirmed', result['quality_reasons'])
        self.assertNotEqual(result['alignment_status'], 'confirmed')

    def test_unconfirmed_binding_not_crosslingual_confirmed(self):
        rows = fixture_rows()
        rows[-1]['alignment_status'] = 'pending'
        result = voice_index([self.audio()], rows, {'test.ps3': 'train'})[0]
        self.assertIn('unconfirmed_source_binding', result['quality_reasons'])
        self.assertNotEqual(result['alignment_status'], 'confirmed')

    def test_japanese_fullwidth_space_preserved(self):
        self.assertEqual(japanese_label('こんにちは。　元気？'), 'こんにちは。　元気？')

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ('../secret', '/absolute', 'D:/secret', 'a\\b', 'a/../b'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    safe_path(Path(directory), value)


if __name__ == '__main__':
    unittest.main()
