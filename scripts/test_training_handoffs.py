"""Meaningful portable handoff regressions, with synthetic data only."""
import json
from pathlib import Path
import tempfile
import unittest
import wave

import training_handoff_tools as tools
from package_training_handoffs import choose_voice_labels, manifest, select_sources


class HandoffTests(unittest.TestCase):
    def fixture(self):
        source = {'id': 'target', 'character': 'mugi', 'source_file': 'sample.ks', 'source_sha256': 'hash',
                  'text': 'こんにちは。', 'context': [{'id': 'past', 'speaker': '肇', 'text': 'おはよう。'}]}
        translated = {'id': 'target', 'character': 'mugi', 'source_file': 'sample.ks', 'source_sha256': 'hash',
                      'text_src': source['text'], 'text_zh': '你好呀。',
                      'context_zh': [{'id': 'past', 'speaker': '肇', 'text': '早上好。'}]}
        return source, translated

    def test_translation_validity_controls_resume_and_mock_rejection(self):
        source, good = self.fixture()
        self.assertIsNone(tools.translation_error(good, source))
        self.assertEqual(tools.translation_error(dict(good, mock=True), source), 'mock_or_qc_placeholder')
        self.assertEqual(tools.translation_error(dict(good, source_sha256='old'), source), 'source_identity_mismatch')
        self.assertEqual(tools.translation_error(dict(good, context_zh=[None]), source), 'invalid_context')
        self.assertEqual(tools.translation_error(None, source), 'invalid_record')
        self.assertEqual(tools.translation_error(dict(good, id=[]), source), 'invalid_record_id')
        self.assertEqual(tools.translation_error(dict(good, context_zh=[{'id': 'future'}]), source), 'context_ids_mismatch')

    def test_duplicate_audio_deduplicates_and_conflicting_transcripts_are_all_excluded(self):
        rows = [['DATASET_ROOT/hika/a.wav','hika','ja','same'],
                ['DATASET_ROOT/hika/a.wav','hika','ja','same'],
                ['DATASET_ROOT/hika/b.wav','hika','ja','first'],
                ['DATASET_ROOT/hika/b.wav','hika','ja','second']]
        chosen, excluded = choose_voice_labels(rows, {('a','same'),('b','first'),('b','second')}, 'hika')
        self.assertEqual(chosen, [('a','same')])
        self.assertEqual(excluded, {'identical_duplicate': 1, 'conflicting_transcripts': 2})

    def test_selection_does_not_include_future_other_branch_or_filtered_context(self):
        base = {'source_file': 'sample.ks', 'segment': 1, 'label': 'daily', 'character': 'hika'}
        rows = [dict(base,id='past',sequence=1,text='普通の朝の挨拶です。',context=[]),
                dict(base,id='future',sequence=3,text='普通の朝の挨拶です。',context=[]),
                dict(base,id='sleep',sequence=0,text='ZZZ',context=[]),
                dict(base,id='branch',sequence=0,segment=0,text='普通の朝の挨拶です。',context=[])]
        target = dict(base,id='target',sequence=2,text='普通の朝の挨拶です。',context=[
            {'id': r['id'], 'speaker': '肇', 'text': r['text']} for r in rows])
        result = select_sources(rows+[target],[target],'hika')
        self.assertEqual([c['id'] for c in result[0]['context']], ['past'])

    def test_convert_ignores_corrupt_tail_and_never_registers_empty_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'source').mkdir();(p/'output').mkdir()
            source, good=self.fixture()
            (p/'package.json').write_text(json.dumps({'slug':'mugi','name':'麦'}),encoding='utf-8')
            (p/'source/dialogue_examples.jsonl').write_text(json.dumps(source)+'\n',encoding='utf-8')
            (p/'system.txt').write_text('synthetic system',encoding='utf-8')
            (p/'glossary.json').write_text(json.dumps({'speaker_map': {'肇':'你'}}),encoding='utf-8')
            path=p/'output/translated.jsonl'
            path.write_text(json.dumps(dict(good,mock=True))+'\n{broken',encoding='utf-8')
            report=tools.convert(p)
            self.assertEqual(report['accepted_translations'],0)
            self.assertNotIn('ousama_mugi_corpus',tools.read_json(p/'output/dataset_info.json'))
            path.write_text(json.dumps(good)+'\n'+json.dumps(good)+'\nnull\n{broken',encoding='utf-8')
            report=tools.convert(p)
            self.assertEqual(report['accepted_translations'],1)
            self.assertEqual(report['malformed_json_lines'],[4])
            self.assertEqual(tools.read_json(p/'output/sharegpt.json')[0]['conversations'][0]['value'],'你：早上好。')

    def test_portable_voice_paths_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'dataset/mugi').mkdir(parents=True);(p/'labels').mkdir()
            (p/'package.json').write_text(json.dumps({'slug':'mugi','kind':'voice'}),encoding='utf-8')
            wav=p/'dataset/mugi/a.wav'
            with wave.open(str(wav),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(32000);w.writeframes(b'\x01\x00'*64000)
            (p/'labels/mugi.list').write_text('dataset/mugi/a.wav|mugi|ja|日文台词\n',encoding='utf-8')
            manifest(p)
            self.assertEqual(tools.verify(p)['training_labels'],1)
            tools.rewrite_paths(p)
            self.assertTrue((p/'train.list').read_text(encoding='utf-8').startswith(wav.as_posix()))
            (p/'labels/mugi.list').write_text('changed',encoding='utf-8')
            with self.assertRaises(ValueError): tools.verify(p)

    def test_path_traversal_rejected(self):
        for relative in ('../outside.wav','/outside','C:/outside','dataset\\outside.wav'):
            with self.assertRaises(ValueError): tools.safe_path(Path('.'),relative)


if __name__=='__main__':
    unittest.main()
