"""Record actual upstream loader membership, including every filtered utterance."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    import yaml
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--role-root', required=True)
    args = parser.parse_args()
    source, role = Path(args.source), Path(args.role_root)
    sys.path[:0] = [str(source), str(source / 'GPT_SoVITS')]
    os.environ['version'] = 'v2Pro'
    from AR.data.dataset import Text2SemanticDataset
    from module.data_utils import TextAudioSpeakerLoader
    from utils import get_hparams_from_file
    from text import cleaned_text_to_sequence
    config = yaml.safe_load((role / 'configs/s1-v2pro.yaml').read_text())
    expected = {Path(line.split('|')[0]).name for line in Path(json.loads(
        (role / 'configs/feature-environment.json').read_text())['inp_text']).read_text().splitlines() if line.strip()}
    s1 = Text2SemanticDataset(config['train_phoneme_path'], config['train_semantic_path'], max_sec=config['data']['max_sec'])
    s2 = TextAudioSpeakerLoader(get_hparams_from_file(str(role / 'configs/s2-v2pro.json')).data, version='v2Pro')
    actual = {'s1': set(s1.item_names), 's2': {row[0] for row in s2.audiopaths_sid_text}}
    semantic_rows = {line.split('\t')[0]: line.split('\t')[1].split()
                     for line in Path(config['train_semantic_path']).read_text().splitlines()[1:] if line.strip()}
    exclusions = {}
    for name in sorted(expected - actual['s1']):
        details = {'stage': 's1', 'utterance': name}
        try:
            phones = cleaned_text_to_sequence(s1.phoneme_data[name][0].split(), 'v2Pro')
            semantic = semantic_rows[name]
            seconds = len(semantic) / s1.hz
            ratio = len(phones) / seconds if seconds else None
            details.update(phoneme_count=len(phones), semantic_count=len(semantic),
                           semantic_seconds=seconds, phonemes_per_second=ratio)
            details['reason'] = ('duration_exceeds_model_limit' if seconds > s1.max_sec else
                'phoneme_sequence_exceeds_model_limit' if len(phones) > s1.max_sec * s1.hz / 2.5 else
                'phoneme_rate_below_upstream_minimum' if ratio is not None and ratio < s1.min_ps_ratio else
                'phoneme_rate_above_upstream_maximum' if ratio is not None and ratio > s1.max_ps_ratio else
                'upstream_loader_filter_see_log')
        except Exception as exc:
            details.update(reason='missing_or_incompatible_features', error=str(exc))
        exclusions[name] = details
    report = {'source_train_utterances': len(expected), 'selection': 'all qualified train rows; no fewshot restriction',
        'stages': {k: {'included_count': len(v), 'included': sorted(v), 'excluded': sorted(expected - v),
                       'exclusion_policy': 'pinned upstream phoneme conversion, duration and phoneme/semantic ratio checks; see runtime log'}
                   for k, v in actual.items()},
        'validation_and_test_used_for_updates': False}
    report['s1_exclusion_details'] = exclusions
    for names in actual.values():
        if not names or not names <= expected:
            raise ValueError('Unexpected runtime dataset membership')
    (role / 'runtime-membership.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('ACTUAL_UPSTREAM_DATASET_MEMBERSHIP_RECORDED', flush=True)


if __name__ == '__main__':
    main()
