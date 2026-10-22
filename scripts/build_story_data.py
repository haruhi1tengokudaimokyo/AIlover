"""Build local evidence without overwriting old builds or distributing assets."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from web.documents.utils.story_pipeline import build_bundle
from build_character_data import is_usable
from mugi_filter import mugi_training_usable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='extracted/scenario_all/scenario/main')
    parser.add_argument('--output', required=True)
    parser.add_argument('--review')
    parser.add_argument('--previous', help='Reuse unchanged parser records from an earlier build')
    parser.add_argument('--voice-root', default='extracted/voice')
    args = parser.parse_args()
    report = build_bundle(args.source, args.output, args.review, args.voice_root, is_usable, args.previous,
                          character_filters={'mugi': mugi_training_usable})
    # Counts only: no original script text in public logs.
    print({k: v for k, v in report.items() if k not in ('source_coverage', 'issues')})


if __name__ == '__main__':
    main()
