"""Mutation checks against real extracted PS3; no game files are bundled here.

Skipped when local read-only extraction is unavailable. Every fixture copies only
the existing source file needed for sn1002 into a fresh temporary package.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import amatsutsumi_extract as reader

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / 'extracted/amatsutsumi/source/aligned_records.jsonl'


@unittest.skipUnless(LEDGER.is_file(), 'Requires locally extracted original PS3 sources')
class ActualSourceMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = [json.loads(line) for line in LEDGER.read_text(encoding='utf-8-sig').splitlines()
                       if line.strip() and json.loads(line)['source_file'] == 'sn1002.ps3']
        if len(cls.records) < 3:
            raise unittest.SkipTest('Complete sn1002 PS3 ledger is unavailable')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.rows = copy.deepcopy(self.records)
        reader.copy_package_sources(ROOT / 'extracted/amatsutsumi/source', self.root, self.rows)

    def test_reparse_complete_real_source(self):
        result = reader.verify_ledger(self.root, self.rows)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['source_records_reparsed'], len(self.rows))

    def test_silent_source_row_deletion_rejected(self):
        with self.assertRaises(ValueError):
            reader.verify_ledger(self.root, self.rows[:-1])

    def test_japanese_transcript_forgery_rejected(self):
        self.rows[0]['ja_text'] = 'これは原作の台詞ではありません。'
        with self.assertRaises(ValueError):
            reader.verify_ledger(self.root, self.rows)

    def test_speaker_identity_forgery_rejected(self):
        self.rows[0]['speaker'] = 'ほたる' if self.rows[0]['speaker'] != 'ほたる' else 'こころ'
        with self.assertRaises(ValueError):
            reader.verify_ledger(self.root, self.rows)

    def test_voice_identity_forgery_rejected(self):
        self.rows[0]['voice_id'] = 'hosn_fake_audio'
        with self.assertRaises(ValueError):
            reader.verify_ledger(self.root, self.rows)

    def test_segment_forgery_rejected(self):
        self.rows[0]['segment'] += 1
        with self.assertRaises(ValueError):
            reader.verify_ledger(self.root, self.rows)

    def test_scene_identifier_forgery_rejected(self):
        self.rows[0]['scene_id'] = 'fabricated.ps3#linear_block_0'
        with self.assertRaises(ValueError):
            reader.verify_ledger(self.root, self.rows)

    def test_scene_safety_forgery_rejected(self):
        self.rows[0]['scene_safety'] = 'explicit' if self.rows[0]['scene_safety'] != 'explicit' else 'safe_screened'
        with self.assertRaises(ValueError):
            reader.verify_ledger(self.root, self.rows)

    def test_dialogue_narration_forgery_rejected(self):
        self.rows[0]['evidence_type'] = 'narration' if self.rows[0]['evidence_type'] == 'dialogue' else 'dialogue'
        with self.assertRaises(ValueError):
            reader.verify_ledger(self.root, self.rows)


if __name__ == '__main__':
    unittest.main()
