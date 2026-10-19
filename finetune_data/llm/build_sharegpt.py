#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_sharegpt.py — 把翻译结果转成 LLaMA-Factory sharegpt 格式。

输入：
  * finetune_data/llm/output/translated.jsonl（translate_corpus.py 的产物）
  * backend/seed_cards/{hika,ayame}.json（中文角色卡：profile 生成 system，
    示例对话直接转成 sharegpt 样本，无需翻译、零成本）

输出（默认都在 finetune_data/llm/output/）：
  * sharegpt.json       —— 翻译语料转出的样本，每行：
      {"conversations":[{"from":"human","value":...},{"from":"gpt","value":...}],
       "system":"<角色人设>"}
  * seed_samples.json   —— 角色卡 5 组手写示例对话转出的样本（每角色 5 条单轮）
  * dataset_info.json   —— LLaMA-Factory 数据集注册片段

上下文为空的记录转成单轮：human 用贴合场景的自然开场（见 EMPTY_CONTEXT_OPENERS）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE / "output" / "translated.jsonl"
DEFAULT_SEED_DIR = PROJECT_ROOT / "backend" / "seed_cards"
DEFAULT_GLOSSARY = HERE / "glossary.json"
DEFAULT_OUT = HERE / "output" / "sharegpt.json"
DEFAULT_SEED_OUT = HERE / "output" / "seed_samples.json"
DEFAULT_DATASET_INFO = HERE / "output" / "dataset_info.json"

# 上下文为空时的自然开场（按角色贴合场景；用户扮演的是豪宅主人「国王大人」）
EMPTY_CONTEXT_OPENERS = {
    "hika": "你就是新来的女仆？",
    "ayame": "你就是菖蒲？绯华经常提起你。",
}
DEFAULT_OPENER = "你好啊。"


# ---------------------------------------------------------------- 角色卡 → system
def profile_to_system(profile: str, name: str) -> str:
    """用角色卡 profile 生成 system：去掉【示例对话】小节（示例单独成样本），保留其余人设。"""
    body = re.sub(r"\n?【示例对话[^】]*】.*?(?=\n【|\Z)", "", profile, flags=re.S).strip()
    return f"你正在扮演角色「{name}」。请严格按以下人设进行角色扮演：\n\n{body}"


def parse_seed_examples(profile: str, char_name: str) -> list:
    """从 profile 的【示例对话】小节解析 用户：/角色： 交替对，返回 [(user, char), ...]。"""
    m = re.search(r"【示例对话[^】]*】\n(.*?)(?=\n【|\Z)", profile, flags=re.S)
    if not m:
        return []
    pairs, pending = [], None
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line:
            continue
        mu = re.match(r"^用户[:：](.*)$", line)
        mc = re.match(rf"^{re.escape(char_name)}[:：](.*)$", line)
        if mu:
            pending = mu.group(1).strip()
        elif mc and pending is not None:
            pairs.append((pending, mc.group(1).strip()))
            pending = None
    return pairs


# ---------------------------------------------------------------- 语料 → sharegpt
def format_context(context_zh: list) -> str:
    """把上下文译稿格式化成剧本式 transcript。说话人名已在翻译管线里映射成中文。"""
    lines = []
    for c in context_zh or []:
        speaker = c.get("speaker_zh") or c.get("speaker") or "旁白"
        text = (c.get("text") or "").strip()
        if not text:
            continue
        if speaker == "旁白":
            lines.append(f"（{text}）")
        else:
            lines.append(f"{speaker}：{text}")
    return "\n".join(lines)


def record_to_sample(rec: dict, system: str) -> dict:
    ctx_text = format_context(rec.get("context_zh"))
    opener = EMPTY_CONTEXT_OPENERS.get(rec.get("character"), DEFAULT_OPENER)
    human_value = ctx_text if ctx_text else opener
    return {
        "conversations": [
            {"from": "human", "value": human_value},
            {"from": "gpt", "value": (rec.get("text_zh") or "").strip()},
        ],
        "system": system,
    }


def validate_sample(sample: dict, where: str, errors: list) -> bool:
    convs = sample.get("conversations")
    ok = (
        isinstance(convs, list) and len(convs) >= 2
        and convs[0].get("from") == "human" and convs[0].get("value", "").strip()
        and convs[-1].get("from") == "gpt" and convs[-1].get("value", "").strip()
        and sample.get("system", "").strip()
    )
    if not ok:
        errors.append(where)
    return ok


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="翻译语料 + 角色卡示例 → LLaMA-Factory sharegpt 数据",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--input", default=str(DEFAULT_INPUT), help="translated.jsonl（不存在时只产种子样本）")
    ap.add_argument("--seed-dir", default=str(DEFAULT_SEED_DIR), help="角色卡目录（hika.json / ayame.json）")
    ap.add_argument("--glossary", default=str(DEFAULT_GLOSSARY), help="glossary.json（预留对照，当前用翻译管线已映射的 speaker_zh）")
    ap.add_argument("--output", default=str(DEFAULT_OUT), help="语料 sharegpt 输出")
    ap.add_argument("--seed-output", default=str(DEFAULT_SEED_OUT), help="角色卡示例 sharegpt 输出")
    ap.add_argument("--dataset-info", default=str(DEFAULT_DATASET_INFO), help="dataset_info.json 输出")
    ap.add_argument("--limit", type=int, default=None, help="只转换前 N 条语料（测试用）")
    args = ap.parse_args()

    errors = []

    # ---- 角色卡：system + 种子样本
    systems, seed_samples = {}, []
    for slug in ("hika", "ayame"):
        card_path = Path(args.seed_dir) / f"{slug}.json"
        card = json.loads(card_path.read_text(encoding="utf-8"))
        system = profile_to_system(card["profile"], card["name"])
        systems[slug] = system
        for user_line, char_line in parse_seed_examples(card["profile"], card["name"]):
            s = {
                "conversations": [
                    {"from": "human", "value": user_line},
                    {"from": "gpt", "value": char_line},
                ],
                "system": system,
            }
            if validate_sample(s, f"seed:{slug}:{user_line[:12]}", errors):
                seed_samples.append(s)
    write_jsonl(Path(args.seed_output), seed_samples)
    print(f"[seed] {len(seed_samples)} 条角色卡示例样本 → {args.seed_output}")

    # ---- 翻译语料
    corpus_samples, skipped_empty, skipped_bad = [], 0, 0
    input_path = Path(args.input)
    if input_path.is_file():
        with input_path.open(encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        if args.limit is not None:
            rows = rows[: args.limit]
        for rec in rows:
            system = systems.get(rec.get("character"))
            if not system:
                skipped_bad += 1
                continue
            if not (rec.get("text_zh") or "").strip():
                skipped_bad += 1
                continue
            if not rec.get("context_zh"):
                skipped_empty += 1
            s = record_to_sample(rec, system)
            if validate_sample(s, f"corpus:{rec.get('id')}", errors):
                corpus_samples.append(s)
        write_jsonl(Path(args.output), corpus_samples)
        print(f"[corpus] {len(corpus_samples)} 条语料样本（空上下文转单轮 {skipped_empty} 条，"
              f"跳过 {skipped_bad} 条）→ {args.output}")
    else:
        print(f"[corpus] 未找到 {input_path}，跳过语料转换（先跑 translate_corpus.py）")

    # ---- dataset_info.json（LLaMA-Factory 注册片段）
    dataset_info = {
        "ousama_corpus": {
            "file_name": Path(args.output).name,
            "formatting": "sharegpt",
            "columns": {"messages": "conversations", "system": "system"},
            "tags": {"role_tag": "from", "content_tag": "value",
                     "user_tag": "human", "assistant_tag": "gpt"},
        },
        "ousama_seed": {
            "file_name": Path(args.seed_output).name,
            "formatting": "sharegpt",
            "columns": {"messages": "conversations", "system": "system"},
            "tags": {"role_tag": "from", "content_tag": "value",
                     "user_tag": "human", "assistant_tag": "gpt"},
        },
    }
    di_path = Path(args.dataset_info)
    di_path.parent.mkdir(parents=True, exist_ok=True)
    di_path.write_text(json.dumps(dataset_info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[dataset_info] → {args.dataset_info}")

    if errors:
        print(f"[validate] {len(errors)} 条样本未通过校验：{errors[:5]}", file=sys.stderr)
        return 1
    print("[validate] 全部样本校验通过（JSON 合法、system 非空、gpt 回复非空）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
