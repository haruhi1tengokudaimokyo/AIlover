# -*- coding: utf-8 -*-
"""
为《王様恋愛》的角色构建聊天 agent 用的干净语料。

    python scripts/build_character_data.py

输入：
    extracted/corpus.jsonl          （parse_scenario.py 产物）
    extracted/voice/voN_xxxx.opus   （xp3.py 提取的语音）

输出（每位角色一个目录）：
    extracted/characters/<slug>/lines_clean.jsonl   干净台词 {"text","voice","file"}
    extracted/characters/<slug>/ref_candidates.txt  音色复刻参考音频候选（含文本）
    extracted/characters/<slug>/stats.txt           自称/称呼/语尾统计
    extracted/characters/<slug>/sample_lines.txt    随机抽样台词（供人工撰写角色卡）
"""
import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

CORPUS = Path('extracted/corpus.jsonl')
VOICE_DIR = Path('extracted/voice')
OUT_ROOT = Path('extracted/characters')

CHARACTERS = {
    'hika': {'char': '緋華', 'full_name': '佐藤緋華'},
    'ayame': {'char': '菖蒲', 'full_name': '藤ヶ丘菖蒲'},
    'mugi': {'char': 'むぎ', 'full_name': '麦'},
}

# 显性内容行级过滤（命中即整行丢弃；●/○ 是官方自我规制的打码，出现即丢弃）
EXPLICIT_RE = re.compile(
    'ちんぽ|ちんこ|まんこ|おまんこ|膣|射精|中出し|種付け|フェラ|パイズリ|アナル|潮吹|絶頂|'
    '子宮|乳首|セックス|性交|勃起|精液|ザーメン|クンニ|手マン|素股|後背位|正常位|騎乗位|'
    'おちん|マンコ|チンポ|イラマ|ごっくん|ぶっかけ|肉棒|性器|陰部|愛液|我慢汁|'
    'エッチ|えっち|おっぱい|パンツ|裸|●|○|手コキ|コキッス|イっちゃ|イかされ|イかせ|'
    'ゴム|オナニー|レイプ|抱いてほしい|抱かれ|抱いてくれ|硬いの|アツいの'
)
# 纯喘息/呻吟行（H 场景典型）
MOAN_RE = re.compile(r'^[あんっんぅぁぇぉゃゅょー…ッ！!？?\s、。~～♥♡]+$')
# 亲吻/性爱拟声词片段（出现即视为 H 场景残留）
SFX_RE = re.compile('ン{2,}|ンッ|ん{3,}|ん[あぐむく]っ|ぅ{4,}|ちゅむ|れちゅ|れりゅ|んちゅ|ちゅく|くちゅ|ぬちゅ|ぐちゅ|ふしゅ')
# 内联标签
TAG_RE = re.compile(r'\[icHeart\]|\[r\]|♥')

# 称呼探测
ADDRESS_TERMS = ['肇', '王様', '王さま', 'ご主人様', 'ご主人さま', 'あなた', 'あんた', '貴様', 'てめえ', 'てめぇ',
                 'お前', 'おまえ', '先輩', '兄様', 'お兄様', 'お兄ちゃん', '旦那様', '旦那さま']


def clean_text(t: str) -> str:
    t = TAG_RE.sub('', t)
    return t.strip()


def is_usable(t: str) -> bool:
    if not t or len(t) < 2:
        return False
    if EXPLICIT_RE.search(t):
        return False
    if SFX_RE.search(t):
        return False
    if MOAN_RE.match(t):
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--char', action='append', choices=CHARACTERS,
                        help='只构建指定角色；不传时保留原 hika/ayame 行为')
    parser.add_argument('--corpus', type=Path, default=CORPUS)
    parser.add_argument('--out-root', type=Path, default=OUT_ROOT)
    args = parser.parse_args()
    rows = [json.loads(l) for l in args.corpus.read_text(encoding='utf-8').splitlines() if l.strip()]
    random.seed(42)

    for slug in args.char or ('hika', 'ayame'):
        info = CHARACTERS[slug]
        name = info['char']
        out_dir = args.out_root / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        mine = [r for r in rows if r['char'] == name]
        if slug == 'mugi' and any('label' not in r or not r.get('source_sha256') for r in mine):
            parser.error('麦的安全提取需要带标签和来源哈希的新解析记录；请运行 scripts/prepare_mugi_training.py')
        kept, dropped = [], 0
        for r in mine:
            t = clean_text(r['text'])
            usable = is_usable(t)
            if slug == 'mugi':
                from mugi_filter import mugi_training_usable
                usable = usable and mugi_training_usable(r)
            if not usable:
                dropped += 1
                continue
            voice_path = None
            if r['voice'] and (VOICE_DIR / f"{r['voice']}.opus").exists():
                voice_path = f"extracted/voice/{r['voice']}.opus"
            kept.append({'text': t, 'voice': voice_path, 'file': r['file'],
                         'source_id': r.get('id'), 'source_location': r.get('source_location'),
                         'source_sha256': r.get('source_sha256')})

        with open(out_dir / 'lines_clean.jsonl', 'w', encoding='utf-8') as f:
            for k in kept:
                f.write(json.dumps(k, ensure_ascii=False) + '\n')

        # ---- 统计 ----
        lines = [k['text'] for k in kept]
        stats = []
        stats.append(f'{info["full_name"]}（{name}） 原始 {len(mine)} 行，过滤 {dropped} 行，保留 {len(kept)} 行')
        stats.append(f'带语音 {sum(1 for k in kept if k["voice"])} 行')

        stats.append('\n== 对主角/他人的称呼 ==')
        for w in ADDRESS_TERMS:
            c = sum(t.count(w) for t in lines)
            if c:
                stats.append(f'  {w}: {c}')

        stats.append('\n== 自称 ==')
        for w in ['あたし', 'アタシ', '私', 'わたくし', 'うち', '僕', '俺']:
            c = sum(1 for t in lines if re.search(r'(^|「|、|\s)' + w + r'(は|が|を|に|の|も|と|って)', t))
            if c:
                stats.append(f'  {w}: {c}')

        stats.append('\n== 高频语尾 TOP 25 ==')
        end = Counter()
        for t in lines:
            t2 = re.sub(r'[。！？…!?\s─—~～っッ]+$', '', t)
            if len(t2) >= 4:
                end[t2[-4:]] += 1
        for k, v in end.most_common(25):
            stats.append(f'  …{k}: {v}')

        (out_dir / 'stats.txt').write_text('\n'.join(stats), encoding='utf-8')

        # ---- 音色参考候选：15~45 字、有语音、无破折号长叹 ----
        cands = [k for k in kept
                 if k['voice'] and 15 <= len(k['text']) <= 45 and '──' not in k['text']]
        random.shuffle(cands)
        with open(out_dir / 'ref_candidates.txt', 'w', encoding='utf-8') as f:
            for k in cands[:60]:
                f.write(f"{k['voice']}\t{k['text']}\n")

        # ---- 抽样台词 ----
        sample = random.sample(kept, min(120, len(kept)))
        with open(out_dir / 'sample_lines.txt', 'w', encoding='utf-8') as f:
            for k in sample:
                f.write(k['text'] + '\n')

        print(f'{name}: 保留 {len(kept)}/{len(mine)} 行 -> {out_dir}')


if __name__ == '__main__':
    main()
