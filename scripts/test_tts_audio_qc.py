"""Offline synthetic-signal tests; no original game/audio data is modified."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from tts_audio_qc import audio_metrics, opus_metadata, quality_flags, quality_reasons


def pcm(values):
    return np.asarray(values, dtype='<i2').tobytes()


def good_metrics():
    # Known two-second signal, rather than a mocked metrics dictionary.
    return audio_metrics(pcm(np.full(64000, 1000)))


class WaveformQuality(unittest.TestCase):
    def test_silence_has_no_activity_and_exact_silence_duration(self):
        metrics = audio_metrics(bytes(64000 * 2))
        self.assertEqual(metrics['samples'], 64000)
        self.assertEqual(metrics['duration_seconds'], 2)
        self.assertEqual(metrics['rms'], 0)
        self.assertEqual(metrics['active_frame_ratio'], 0)
        self.assertEqual(metrics['leading_silence_seconds'], 2)
        self.assertEqual(metrics['trailing_silence_seconds'], 2)
        self.assertIn('rms_below_100', quality_reasons(metrics, 'おはよう。'))
        self.assertEqual(metrics['isolation_music_overlap_status'], 'not_measured_requires_listening')

    def test_duration_limits_are_inclusive_and_exclusions_are_strict(self):
        for seconds in (1, 20):
            self.assertFalse(any(reason.startswith('duration_') for reason in
                             quality_reasons(audio_metrics(pcm(np.full(32000 * seconds, 1000))), 'はい。')))
        self.assertIn('duration_too_short', quality_reasons(audio_metrics(pcm(np.full(31999, 1000))), 'はい。'))
        self.assertIn('duration_too_long', quality_reasons(audio_metrics(pcm(np.full(640001, 1000))), 'はい。'))

    def test_saturated_negative_int16_does_not_overflow(self):
        metrics = audio_metrics(pcm(np.full(32000, -32768)))
        self.assertEqual(metrics['rms'], 32768)
        self.assertEqual(metrics['peak_ratio'], 1)
        self.assertEqual(metrics['clipped_sample_ratio'], 1)
        self.assertIn('clipped_sample_ratio_above_0_005', quality_reasons(metrics, 'こんにちは。'))

    def test_high_peak_is_only_flag_without_sustained_clipping(self):
        values = np.full(64000, 1000)
        values[32000] = 32500
        metrics = audio_metrics(pcm(values))
        self.assertIn('high_peak', quality_flags(metrics))
        self.assertEqual(quality_reasons(metrics, 'はい。'), [])
        self.assertEqual(metrics['clipped_sample_ratio'], 0)

    def test_boundary_flag_requires_rms_and_absolute_endpoint(self):
        values = np.zeros(64000, dtype=np.int16)
        values[:320] = -2000
        metrics = audio_metrics(pcm(values))
        self.assertIn('potential_cut_boundary', quality_flags(metrics))
        self.assertLess(metrics['start_sample_ratio'], -.05)
        values[0] = 0
        self.assertNotIn('potential_cut_boundary', quality_flags(audio_metrics(pcm(values))))

    def test_low_active_ratio_and_long_silence_are_separate(self):
        values = np.zeros(128000, dtype=np.int16)
        values[64000:64320] = 5000
        metrics = audio_metrics(pcm(values))
        self.assertAlmostEqual(metrics['active_frame_ratio'], 1 / 400)
        self.assertEqual(metrics['leading_silence_seconds'], 2)
        self.assertAlmostEqual(metrics['trailing_silence_seconds'], 1.99)
        self.assertIn('active_frame_ratio_below_0_05', quality_reasons(metrics, 'はい。'))
        self.assertIn('excess_silence', quality_flags(metrics))

    def test_complete_short_japanese_sentences_are_preserved(self):
        metrics = good_metrics()
        for text in ['はい。', 'うん。', 'いいよ。', 'そうだね。', 'ありがとう。', 'ふうん。', 'ええ。',
                     'はあ？', 'おはよう。', 'ちょうだい。', 'はーい。', 'ふふ、そうなの？']:
            self.assertEqual(quality_reasons(metrics, text), [], text)

    def test_only_complete_common_nonverbal_utterances_are_rejected(self):
        metrics = good_metrics()
        for text in ['はぁ……', 'んんっ……', 'ちゅっちゅ', 'ハァ……フウ……', 'ZZZ', 'ＺＺ……',
                     'はぁっ、ふぅ、あぁっ……', 'むちゅぅ～～']:
            self.assertIn('nonverbal_utterance', quality_reasons(metrics, text), text)
        self.assertEqual(quality_reasons(metrics, 'はぁ、困ったね。'), [])

    def test_empty_and_punctuation_text_are_distinguished(self):
        metrics = good_metrics()
        self.assertEqual(quality_reasons(metrics, None), ['empty_text'])
        self.assertEqual(quality_reasons(metrics, '   '), ['empty_text'])
        self.assertEqual(quality_reasons(metrics, '……！？♡'), ['punctuation_only_text'])

    def test_pcm_hash_covers_every_byte_and_outputs_are_json_safe(self):
        raw = pcm([1, -32768, 4, 500])
        metrics = audio_metrics(raw)
        self.assertEqual(metrics['pcm_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(metrics['pcm_sha256'], audio_metrics(raw[:-2])['pcm_sha256'])
        self.assertEqual(metrics['samples'], 4)
        json.dumps(metrics, allow_nan=False)

    def test_empty_pcm_and_incomplete_sample_are_not_silently_modified(self):
        empty = audio_metrics(b'')
        self.assertEqual(empty['duration_seconds'], 0)
        self.assertEqual(empty['pcm_sha256'], hashlib.sha256(b'').hexdigest())
        self.assertEqual(empty['peak_ratio'], 0)
        with self.assertRaises(ValueError):
            audio_metrics(b'\x00')
        with self.assertRaises(ValueError):
            audio_metrics(b'\x00\x00', 0)

    def test_partial_frame_duration_and_activity_use_real_samples(self):
        metrics = audio_metrics(pcm(np.r_[np.zeros(320), np.full(100, 1000)]))
        self.assertEqual(metrics['samples'], 420)
        self.assertAlmostEqual(metrics['duration_seconds'], 420 / 32000)
        self.assertEqual(metrics['leading_silence_seconds'], .01)
        self.assertEqual(metrics['trailing_silence_seconds'], 0)
        self.assertEqual(metrics['active_frame_ratio'], .5)

    def test_clip_ratio_boundary_is_strict(self):
        values = np.full(32000, 1000)
        values[1000:1160] = 32760
        self.assertNotIn('clipped_sample_ratio_above_0_005', quality_reasons(audio_metrics(pcm(values)), 'はい。'))
        values[1160] = 32760
        self.assertIn('clipped_sample_ratio_above_0_005', quality_reasons(audio_metrics(pcm(values)), 'はい。'))

    def test_opus_granule_clock_and_preskip_are_header_only(self):
        def page(body, granule):
            return (b'OggS' + bytes([0, 0]) + struct.pack('<QII', granule, 3, 0)
                    + bytes(4) + bytes([1, len(body)]) + body)
        head = b'OpusHead' + bytes([1, 1]) + struct.pack('<HIhB', 312, 24000, 0, 0)
        raw = page(head, 0) + page(b'not-decoded-audio', 48312)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.opus'
            path.write_bytes(raw)
            metrics = opus_metadata(path)
        self.assertEqual(metrics['duration_seconds'], 1)
        self.assertEqual(metrics['input_sample_rate_hint'], 24000)
        self.assertEqual(metrics['decoded_sample_rate'], 48000)
        self.assertEqual(metrics['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertFalse(metrics['audio_decoding_performed'])


if __name__ == '__main__':
    unittest.main()
