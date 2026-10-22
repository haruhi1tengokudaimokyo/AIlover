"""Mugi preparation safeguards; offline, fixture-only, never rewrites datasets."""
import importlib.util
from pathlib import Path
import unittest

from prepare_mugi_training import preceding_safe_context
from mugi_filter import mugi_training_usable

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mugi_llm', ROOT / 'finetune_data/mugi/build_llm.py')
llm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm)


class TrainingSafeguards(unittest.TestCase):
    def test_mugi_filter_rejects_intimate_scenes_and_nonverbal_sound(self):
        self.assertFalse(mugi_training_usable({'label': 'H_Start', 'text': 'This otherwise safe line.'}))
        self.assertFalse(mugi_training_usable({'label': 'Start', 'text': 'はぁっ……ふぅ……あぁ……'}))
        self.assertFalse(mugi_training_usable({'label': 'Start', 'text': 'しょんなこと────ＺＺＺ'}))
        self.assertTrue(mugi_training_usable({'label': 'Start', 'text': 'はいはい、わかったよ。'}))

    def test_mugi_filter_handles_explicit_start_label_without_broad_body_word_filter(self):
        for text in ['乳輪はみ出てるよ～？', '半乳メイドのくせによく言うね', 'ちゃんと性欲も強いよ？',
                     '来葉なんて適当に乳か尻叩けばいい音鳴りそう', 'お股のぬるぬるはせーし',
                     'メイド３Ｐのお決まり', 'ヌキヌキしてあげよう', '全部脱いじゃおっか',
                     '早漏', '孕ませ', '童貞捨て', '精通', 'ギンギン', 'ラブホ', '抜いてあげない',
                     'ヤリ捨て', 'ちっぱい', 'いっぱい抱いて', '私のことも脱がさないの？']:
            self.assertFalse(mugi_training_usable({'label': 'Start', 'text': text}))
        self.assertTrue(mugi_training_usable({'label': 'Start', 'text': '自分の胸に手を当ててよく考えてみて'}))
        self.assertTrue(mugi_training_usable({'label': 'Start', 'text': '抱きしめてもらってるだけでも幸せだよ。'}))

    def test_context_excludes_target_future_and_other_branches(self):
        base = {'source_file': '0_1.ks', 'segment': 1}
        indexed = {name: dict(base, sequence=sequence, text='This is dialogue.') for name, sequence in
                   [('past', 1), ('target', 2), ('future', 3), ('branch', 0), ('other_file', 0)]}
        indexed['branch']['segment'] = 0
        indexed['other_file']['source_file'] = '0_2.ks'
        row = dict(base, id='target', sequence=2,
                   context=[{'id': name, 'text': 'This is dialogue.'} for name in indexed])
        self.assertEqual([c['id'] for c in preceding_safe_context(row, indexed)], ['past'])

    def test_context_uses_full_row_mugi_filter(self):
        base = {'source_file': '0_1.ks', 'segment': 1}
        indexed = {name: dict(base, sequence=i, text=text, label=label) for i, (name, text, label) in enumerate([
            ('sleep', 'ZZZ', 'Start'), ('breath', 'はぁっ……ふぅ……', 'Start'),
            ('intimate', 'Otherwise ordinary dialogue.', 'H_Start'),
            ('explicit', 'ちゃんと性欲も強いよ？', 'Start'), ('safe', '普通の朝の挨拶だよ。', 'Start')])}
        row = dict(base, id='target', sequence=10,
                   context=[{'id': name, 'text': r['text']} for name, r in indexed.items()])
        self.assertEqual([c['id'] for c in preceding_safe_context(row, indexed)], ['safe'])

    def fixture(self):
        source = {'id': 'target', 'source_file': '0_1.ks', 'text': 'こんにちは。',
                  'context': [{'id': 'past', 'speaker': '肇', 'text': 'おはよう。'}]}
        translated = {'id': 'target', 'source_file': '0_1.ks', 'character': 'mugi',
                      'text_src': source['text'], 'text_zh': '你好呀。',
                      'context_zh': [{'id': 'past', 'speaker': '肇', 'text': '早上好。'}]}
        return source, translated

    def test_accepts_only_structurally_aligned_real_translation(self):
        source, translated = self.fixture()
        self.assertIsNone(llm.validation_error(translated, source))
        translated['mock'] = True
        self.assertEqual(llm.validation_error(translated, source), 'mock_or_qc_placeholder')

    def test_rejects_future_context_and_untranslated_text(self):
        source, translated = self.fixture()
        translated['context_zh'][0]['id'] = 'future'
        self.assertEqual(llm.validation_error(translated, source), 'context_ids_mismatch')
        translated['context_zh'][0]['id'] = 'past'
        translated['text_zh'] = source['text']
        self.assertEqual(llm.validation_error(translated, source), 'target_not_translated_to_chinese')

    def test_rejects_source_drift(self):
        source, translated = self.fixture()
        translated['text_src'] = 'Something from another script.'
        self.assertEqual(llm.validation_error(translated, source), 'source_mismatch')


if __name__ == '__main__':
    unittest.main()
