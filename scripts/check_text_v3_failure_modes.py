"""Exercise semantic/provenance gates on disposable package copies, never V2.

Rehash mutations deliberately: rejection must come from the invariant being
tested, rather than merely detecting an outdated outer checksum.
"""
import argparse
from pathlib import Path
import shutil

import text_corpus_v3_common as policy


def canonical_edit(root, operation):
    rows = policy.jsonl_read(root / 'provenance/canonical.jsonl')
    operation(rows)
    policy.jsonl_write(root / 'provenance/canonical.jsonl', rows)


def future_context(root):
    def alter(rows):
        rows[0]['context_ids'][-1] = rows[0]['target_id']
    canonical_edit(root, alter)


def fabricated_context(root):
    def alter(rows):
        rows[0]['sample']['conversations'][0]['value'] += '\n【此前剧情】麦：这是并不存在的前序台词。'
        rows[0]['payload_sha256'] = policy.payload_sha(rows[0]['sample'])
    canonical_edit(root, alter)


def speaker_mismatch(root):
    records = policy.jsonl_read(root / 'source/records.jsonl')
    ident = policy.jsonl_read(root / 'provenance/canonical.jsonl')[0]['target_id']
    next(r for r in records if r['id'] == ident)['speaker'] = '肇'
    policy.jsonl_write(root / 'source/records.jsonl', records)


def split_mismatch(root):
    def alter(rows):
        rows[0]['split'] = 'test' if rows[0]['split'] != 'test' else 'train'
    canonical_edit(root, alter)


def unreviewed_synthetic(root):
    candidate = next(r for r in policy.jsonl_read(root / 'synthetic/candidates.jsonl') if r['split'] == 'train')
    path = root / 'sft/mixed_sft_v3/train'
    samples, ids = policy.json_read(path.with_suffix('.json')), policy.json_read(root / 'sft/mixed_sft_v3/train_ids.json')
    samples.append(candidate['sample'])
    ids.append(candidate['sample_id'])
    policy.json_write(path.with_suffix('.json'), samples)
    policy.json_write(root / 'sft/mixed_sft_v3/train_ids.json', ids)


def malformed_json(root):
    (root / 'qa.json').write_text('{malformed json', encoding='utf-8')


def baseline_changed(root):
    path = root / 'baseline_reference/system.txt'
    path.write_text(path.read_text(encoding='utf-8') + '\n偷偷改变 V2。', encoding='utf-8')


def synthetic_from_heldout(root):
    records = policy.jsonl_read(root / 'provenance/canonical.jsonl')
    heldout = next(r for r in records if r['split'] == 'test')
    candidates = policy.jsonl_read(root / 'synthetic/candidates.jsonl')
    candidates[0]['canon_fact_refs'] = [heldout['target_id']]
    policy.jsonl_write(root / 'synthetic/candidates.jsonl', candidates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, destination = args.package.resolve(), args.output.resolve()
    workspace = Path(__file__).resolve().parents[1]
    if destination.exists() or not destination.is_relative_to(workspace / 'finetune_data/text_v3'):
        raise ValueError('Use a fresh disposable output inside finetune_data/text_v3')
    destination.mkdir(parents=True)
    policy.verify_package(source)
    results = []
    for mutate in (future_context, fabricated_context, speaker_mismatch, split_mismatch,
                   unreviewed_synthetic, malformed_json, baseline_changed, synthetic_from_heldout):
        folder = destination / mutate.__name__
        shutil.copytree(source, folder, ignore=shutil.ignore_patterns('__pycache__'))
        # Use the current verifier policy while developing the final deliverable.
        mutate(folder)
        policy.manifest_write(folder)
        try:
            policy.verify_package(folder)
        except (ValueError, KeyError, TypeError) as error:
            results.append({'mutation': mutate.__name__, 'status': 'correctly_rejected', 'reason': str(error)})
            print(mutate.__name__ + ': rejected — ' + str(error), flush=True)
        else:
            raise AssertionError('Verifier accepted corrupt package: ' + mutate.__name__)
    policy.json_write(destination / 'failure_mode_results.json', results)


if __name__ == '__main__':
    main()
