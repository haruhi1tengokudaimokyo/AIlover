# -*- coding: utf-8 -*-
"""
解析 KAG 剧本，抽取「角色名 + 语音编号 + 台词」三元组，生成语料 JSONL。

    python scripts/parse_scenario.py

输出：
    extracted/corpus.jsonl     每行 {"file","char","voice","text"}
    并打印各角色台词数统计
"""
import glob
import json
import re
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from web.documents.utils.story_pipeline import decode_source, parse_script

SRC = Path('extracted/scenario_all/scenario')
OUT = Path('extracted/corpus.jsonl')

# [名字 vo=voN_xxxx] 或 [名字] 或 [地]（旁白）
TAG_RE = re.compile(r'\[([^\]\s>/]+?)(?:\s+vo=(vo\d+_\d+))?\]')
TEXT_RE = re.compile(r'\[>>\](.+?)\[<<\]', re.S)

SKIP_CHARS = {'地', 'hh'}  # 地=旁白


def decode(path):
    return decode_source(path)[0]


def parse_file(path):
    """Compatibility fields plus provenance; prefer build_story_data for new builds."""
    path = Path(path).resolve()
    root = SRC.resolve() if path.is_relative_to(SRC.resolve()) else path.parent
    records, _ = parse_script(path, root)
    return [dict(row, file=path.name, char=row['speaker'], voice=row['voice_id'], text=row['raw_text']) for row in records]


def main():
    all_rows = []
    files = sorted(glob.glob(str(SRC / 'main' / '*.ks')))
    for p in files:
        all_rows.extend(parse_file(Path(p)))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    # 统计：角色台词数 / 语音数
    cnt = Counter(r['char'] for r in all_rows if r['char'] not in SKIP_CHARS)
    vcnt = Counter(r['char'] for r in all_rows if r['voice'])
    print(f'总台词 {len(all_rows)} 条，写入 {OUT}')
    print('角色台词数 / 带语音数:')
    for name, c in cnt.most_common(20):
        print(f'  {name}: {c} / {vcnt.get(name, 0)}')

    # 语音前缀 -> 角色名 映射
    pref = {}
    for r in all_rows:
        if r['voice']:
            p = r['voice'].split('_')[0]
            pref.setdefault(p, Counter())[r['char']] += 1
    print('语音前缀 -> 角色:')
    for p, c in sorted(pref.items()):
        print(f'  {p}: {c.most_common(3)}')


if __name__ == '__main__':
    main()
