"""No network/real shutdown: regression checks for the backup gate."""
import copy
import hashlib
import json
import unittest

from finalize_shutdown import validate


class ShutdownGateTests(unittest.TestCase):
    def fixture(self):
        entries = [{'role': r, 'kind': k, 'archive': f'/outputs/{r}-{k}.zip', 'sha256': 'abc', 'bytes': 10}
                   for r in ('mugi', 'hotaru', 'hika', 'ayame') for k in ('text', 'voice')]
        entries.append({'kind': 'shared_base', 'archive': '/outputs/shared.zip', 'sha256': 'def', 'bytes': 20})
        raw = json.dumps({'status': 'all_complete', 'artifacts': entries})
        receipt = {'status': 'all_verified_on_local_disk', 'manifest_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                   'artifacts': [{**e, 'local_sha256': e['sha256'], 'zip_verified': True} for e in entries]}
        return raw, receipt

    def test_complete_valid_receipt(self):
        self.assertEqual(len(validate(*self.fixture())['artifacts']), 9)

    def test_reject_missing_model(self):
        raw, receipt = self.fixture()
        receipt['artifacts'].pop(0)
        with self.assertRaises((AssertionError, KeyError)):
            validate(raw, receipt)

    def test_reject_damaged_local_model(self):
        raw, receipt = self.fixture()
        receipt['artifacts'][0]['local_sha256'] = 'wrong'
        with self.assertRaises(AssertionError):
            validate(raw, receipt)

    def test_reject_stale_receipt(self):
        raw, receipt = self.fixture()
        receipt['manifest_sha256'] = 'old'
        with self.assertRaises(AssertionError):
            validate(raw, receipt)

    def test_reject_incomplete_training(self):
        raw, receipt = self.fixture()
        manifest = json.loads(raw)
        manifest['status'] = 'running'
        raw = json.dumps(manifest)
        receipt['manifest_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
        with self.assertRaises(AssertionError):
            validate(raw, receipt)


if __name__ == '__main__':
    unittest.main()
