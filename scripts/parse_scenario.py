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

SRC = Path('extracted/scenario_all/scenario')
OUT = Path('extracted/corpus.jsonl')

# [名字 vo=voN_xxxx] 或 [名字] 或 [地]（旁白）
TAG_RE = re.compile(r'\[([^\]\s>/]+?)(?:\s+vo=(vo\d+_\d+))?\]')
TEXT_RE = re.compile(r'\[>>\](.+?)\[<<\]', re.S)

SKIP_CHARS = {'地', 'hh'}  # 地=旁白


def decode(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8', 'utf-16-le', 'shift-jis'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def parse_file(path):
    """逐行解析：名字标签行之后跟着 [>>]台词[<<] 行"""
    text = decode(path)
    rows = []
    cur_char = None
    cur_voice = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(';') or line.startswith('@') or line.startswith('*'):
            continue
        m = TAG_RE.match(line)
        if m and not line.startswith('[>>'):
            name, voice = m.group(1), m.group(2)
            cur_char, cur_voice = name, voice
            # 同一行可能直接带台词
            rest = line[m.end():]
            tm = TEXT_RE.search(rest)
            if tm and cur_char:
                rows.append({'file': path.name, 'char': cur_char,
                             'voice': cur_voice, 'text': tm.group(1).strip()})
            continue
        tm = TEXT_RE.search(line)
        if tm and cur_char:
            rows.append({'file': path.name, 'char': cur_char,
                         'voice': cur_voice, 'text': tm.group(1).strip()})
            cur_voice = None
    return rows


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
