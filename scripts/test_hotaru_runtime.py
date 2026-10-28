"""Cross-game data isolation and byte preservation in the runtime installer."""
import json
from pathlib import Path
import tempfile
import unittest

from install_hotaru_runtime import build_runtime


def write(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


class HotaruRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / 'old'
        self.old.mkdir()
        for name in ('records', 'dialogue_examples'):
            write(self.old / (name + '.jsonl'), [dict(id='old-hika', character='hika', text='old source')])
        (self.old / 'story_knowledge.jsonl').write_text('', encoding='utf-8')
        (self.old / 'voice_manifest.jsonl').write_text('', encoding='utf-8')
        self.source = self.root / 'source'
        self.source.mkdir()
        self.row = dict(id='amatsutsumi-hotaru-001', character='hotaru', text='汉化来源',
                        source_file='scene.ps3', source_location={'byte_offset': 60}, source_sha256='a' * 64, voice_id='ho_001')
        write(self.source / 'source_records.jsonl', [self.row])
        write(self.source / 'dialogue_examples.jsonl', [dict(self.row, evidence_type='style')])
        write(self.source / 'lines_clean.jsonl', [dict(text='汉化来源', voice='ho_001', file='scene.ps3')])

    def test_old_evidence_bytes_and_reviewed_lore_are_preserved(self):
        before = {path.name: path.read_bytes() for path in self.old.iterdir()}
        output = self.root / 'new'
        report = build_runtime(self.source, self.old, output)
        self.assertEqual(report['counts'], {'hika': 1, 'hotaru': 1})
        for name, raw in before.items():
            self.assertEqual((self.old / name).read_bytes(), raw)
            self.assertTrue((output / name).read_bytes().startswith(raw))
        self.assertEqual((output / 'story_knowledge.jsonl').read_bytes(), before['story_knowledge.jsonl'])

    def test_cross_game_id_collision_is_rejected(self):
        row = dict(self.row, id='old-hika')
        write(self.source / 'source_records.jsonl', [row])
        write(self.source / 'dialogue_examples.jsonl', [dict(row, evidence_type='style')])
        with self.assertRaisesRegex(ValueError, 'collision'):
            build_runtime(self.source, self.old, self.root / 'new')

    def test_style_cannot_forge_a_different_source_reply(self):
        write(self.source / 'dialogue_examples.jsonl', [dict(self.row, text='forged target', evidence_type='style')])
        with self.assertRaisesRegex(ValueError, 'exact source'):
            build_runtime(self.source, self.old, self.root / 'new')


if __name__ == '__main__':
    unittest.main()
