"""Compare two independently verified builds and record final delivery evidence."""
import argparse
import csv
from collections import Counter
from pathlib import Path

from text_corpus_v3_common import json_read, json_write, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', required=True, type=Path)
    parser.add_argument('--second', required=True, type=Path)
    parser.add_argument('--record-delivery', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    first, second = args.first.resolve(), args.second.resolve()
    if first == second or any(not p.is_relative_to(root / 'finetune_data/text_v3') for p in (first, second)):
        raise ValueError('Use two independent V3 build directories')
    evidence = {'independent_rebuild': 'passed', 'byte_identical_zip_archives': {}, 'protected_inputs_rechecked': 0}
    for label in ('Hika', 'Ayame', 'Mugi'):
        name = f'AIlover_{label}_Text_V3.zip'
        left, right = sha(first / name), sha(second / name)
        if left != right:
            raise ValueError('Rebuild hash differs: ' + name)
        evidence['byte_identical_zip_archives'][name] = left
    protected = json_read(first / 'protected_inputs_before.json')
    if any(sha(Path(path)) != value for path, value in protected.items()):
        raise ValueError('Protected V2/game/voice input changed after building')
    evidence['protected_inputs_rechecked'] = len(protected)
    with (first / 'AIlover_Text_Corpus_V3_Review.csv').open(encoding='utf-8-sig', newline='') as f:
        counts = Counter(r['character'] for r in csv.DictReader(f))
    if set(counts) != {'hika', 'ayame', 'mugi'} or any(n < 50 for n in counts.values()):
        raise ValueError('Insufficient review coverage')
    evidence['review_rows_per_character'] = dict(counts)
    json_write(second / 'independent_rebuild_comparison.json', evidence)
    if args.record_delivery:
        for name, value in evidence['byte_identical_zip_archives'].items():
            if sha(root / name) != value:
                raise ValueError('Published root archive differs')
        for destination in (first, root):
            checks_path = destination / 'AIlover_Text_Corpus_V3_Checks.json'
            checks = json_read(checks_path)
            checks['reproducibility'] = evidence
            json_write(checks_path, checks)
            report_path = destination / 'AIlover_Text_Corpus_V3_Report.md'
            marker = '\n## 独立重建复现核对\n'
            report = report_path.read_text(encoding='utf-8').split(marker)[0]
            report += marker + '\n在第二个全新目录重新提取、构建、打包并解压验证；三个 ZIP 与正式交付逐字节相同（SHA256 完全一致）。\n'
            report += f"再次复核 {len(protected)} 个受保护输入，均未改变；人工审查条数 {dict(counts)}。\n"
            report += '复核命令：`python -B -X utf8 scripts/compare_text_v3_builds.py --first 首次构建目录 --second 独立重建目录`。\n'
            report_path.write_text(report, encoding='utf-8')
    print(evidence)


if __name__ == '__main__':
    main()
