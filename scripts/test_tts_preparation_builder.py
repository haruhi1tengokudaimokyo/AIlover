"""Prevent a single-role handoff from requiring other roles' references."""
import csv
from pathlib import Path
import tempfile
import unittest

from build_tts_preparation_v1 import review_csv


class SingleRoleReviewTests(unittest.TestCase):
    def check_role(self, slug):
        row = {'character_id': slug, 'utterance_id': slug + '_001',
               'audio_path': 'tts_adaptation/' + slug + '/audio/001.wav',
               'audio_path_scope': 'package', 'split': 'reference',
               'ja_text': 'こんにちは。', 'zh_text': '你好。', 'zh_variants': [],
               'duration_seconds': 5.0, 'quality_status': 'accepted',
               'quality_reasons': [], 'quality_flags': []}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'audit.csv'
            counts = review_csv(target, [row], {slug: [{'utterance_id': row['utterance_id']}]})
            self.assertEqual(counts, {slug: 1})
            with target.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['character_id'], slug)
            self.assertEqual(rows[0]['human_ja_match'], '')

    def test_hika(self):
        self.check_role('hika')

    def test_ayame(self):
        self.check_role('ayame')

    def test_mugi(self):
        self.check_role('mugi')


if __name__ == '__main__':
    unittest.main()
