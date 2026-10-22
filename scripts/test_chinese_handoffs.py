"""Regression checks for real conversation pairing and cross-language annotations."""
import json
from pathlib import Path
import tempfile
import unittest

import chinese_handoff_tools as tools
from prepare_chinese_handoffs import pair_examples, chinese_ok, chinese_system


def row(ident, speaker, text, character=None, segment=1, filename='scene.ks', evidence='dialogue'):
    return {'id': ident, 'speaker': speaker, 'text': text, 'character': character,
            'source_file': filename, 'segment': segment, 'source_location': {'line_start': 1, 'line_end': 1},
            'source_sha256': 'hash', 'voice_id': None, 'evidence_type': evidence}


class PairingTests(unittest.TestCase):
    def dataset(self):
        rows = []
        for i in range(20):
            rows += [row(f'u{i}', '肇', f'今天想做第{i}件什么事？', filename=f'{i}.ks'),
                     row(f'a{i}', '麦', f'主人，我们一起做第{i}件事吧。', 'mugi', filename=f'{i}.ks')]
        return rows

    def test_actual_protagonist_turn_and_file_heldout(self):
        rows = self.dataset()
        safe = [r for r in rows if r['character'] == 'mugi']
        train, val, _ = pair_examples(rows, safe, 'mugi', '只说中文。')
        self.assertEqual(len(train) + len(val), 20)
        self.assertFalse({r['source_file'] for r in train} & {r['source_file'] for r in val})
        for record in train + val:
            self.assertEqual(record['sample']['conversations'][0]['value'],
                             next(r['text'] for r in rows if r['id'] == record['input_id']))

    def test_does_not_cross_segment_or_other_speaker(self):
        rows = self.dataset()
        rows += [row('u20', '肇', '你现在有空吗？', filename='extra.ks'),
                 row('other', '绯华', '我有事情要说。', 'hika', filename='extra.ks'),
                 row('bad', '麦', '我知道啦主人。', 'mugi', filename='extra.ks'),
                 row('bad2', '麦', '这句话属于另一段。', 'mugi', segment=2, filename='extra.ks')]
        train, val, rejected = pair_examples(rows, [r for r in rows if r['character'] == 'mugi'], 'mugi', '中文。')
        self.assertNotIn('bad', {r['target_id'] for r in train + val})
        self.assertNotIn('bad2', {r['target_id'] for r in train + val})
        self.assertEqual(rejected['no_adjacent_protagonist_turn'], 2)

    def test_chinese_text_quality(self):
        self.assertTrue(chinese_ok('主人，今天一起吃晚饭吧。'))
        for text in ('こんにちは', '你好ですね', '', 'hello', '[font]你好', '你说的是身体相通吧？',
                     '嗯～～～～喵？', '我们做点大人才会做的事吧。'):
            self.assertFalse(chinese_ok(text))

    def test_system_preserves_chinese_words_containing_shared_han(self):
        system = chinese_system('私下里并不自私，原文自称「私」，称呼「ご主人様」。')
        self.assertIn('私下里并不自私', system)
        self.assertIn('「我」', system)
        self.assertNotRegex(system, tools.KANA)


class PortableToolsTests(unittest.TestCase):
    def test_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('../secret', '/etc/passwd', 'C:/secret', '..\\secret'):
                with self.assertRaises(ValueError):
                    tools.contained(Path(tmp), name)

    def test_language_contract_preserves_real_japanese_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text(json.dumps({'slug': 'mugi'}), encoding='utf-8')
            (root / 'reference').mkdir()
            wav = root / 'reference/mugi_ref_1.wav'
            wav.write_bytes(b'reference')
            wav.with_suffix('.txt').write_text('ご主人様', encoding='utf-8')
            request = tools.tts_request(root, '主人，今天辛苦啦。')
            self.assertEqual((request['prompt_lang'], request['text_lang']), ('ja', 'zh'))
            self.assertEqual(request['prompt_text'], 'ご主人様')
            with self.assertRaises(ValueError):
                tools.tts_request(root, 'こんにちは')

    def test_evaluation_reports_missing_and_does_not_claim_similarity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'chinese_eval').mkdir()
            (root / 'chinese_eval/utterances.jsonl').write_text(
                json.dumps({'id': 'a', 'text': '你好呀'}) + '\n' + json.dumps({'id': 'b', 'text': '晚上好'}), encoding='utf-8')
            transcripts = root / 'actual.jsonl'
            transcripts.write_text(json.dumps({'id': 'a', 'asr_text': '你好啊'}), encoding='utf-8')
            result = tools.evaluate(root, transcripts)
            self.assertEqual(result['missing_cases'], 1)
            self.assertAlmostEqual(result['chinese_CER'], .3333)
            self.assertEqual(result['voice_similarity'], 'not_measured')
            transcripts.write_text(json.dumps({'id': 'unknown', 'asr_text': '你好'}), encoding='utf-8')
            with self.assertRaises(ValueError):
                tools.evaluate(root, transcripts)

    def test_remote_inference_not_implicit(self):
        with self.assertRaises(ValueError):
            tools.synthesize(Path('.'), '你好', 'https://example.com', 1)


if __name__ == '__main__':
    unittest.main()
