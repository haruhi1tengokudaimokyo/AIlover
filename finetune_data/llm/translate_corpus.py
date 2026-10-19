#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""translate_corpus.py — 日文 galgame 台词 → 中文 翻译管线（sharegpt 微调数据第一步）。

功能：
  * 读取 backend/story_data/dialogue_examples.jsonl，每条记录把角色台词 + 上下文
    一次性发给 OpenAI 兼容接口（默认阿里云百炼 DashScope），要求返回 JSON 保持结构。
  * glossary.json 注入 prompt：galgame 汉化腔、保留语气词、译名/自称/口癖严格对照。
  * 断点续跑：输出 jsonl 追加写入，重跑时跳过已完成 id。
  * --mock：不调用 API，把日文原文当中文占位输出（零网络验证管线）。
  * 并发 4 线程（--workers 可调），429/5xx 指数退避重试。
  * 质检内嵌：译文残留平假名/片假名 → 写入 qc_failed.jsonl 并从主输出剔除。
    （--mock 模式下占位输出必然含日文，质检只记录不剔除。）

API 配置（绝不打印 key）：
  启动时读取项目根 .env（手写 key=value 解析），或环境变量 API_KEY / API_BASE / MODEL。
  .env 不存在且未提供环境变量时，必须使用 --mock，否则报错退出。

用法：
  python translate_corpus.py --mock --limit 20
  python translate_corpus.py                 # 全量 3272 条（需要 .env 里的 API_KEY）
  python translate_corpus.py --limit 100 --workers 4
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------------------------------------------------------- 路径默认值
PROJECT_ROOT = Path(__file__).resolve().parents[2]          # D:\AIlover
DEFAULT_INPUT = PROJECT_ROOT / "backend" / "story_data" / "dialogue_examples.jsonl"
DEFAULT_GLOSSARY = Path(__file__).resolve().parent / "glossary.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "translated.jsonl"
DEFAULT_QC_FAILED = Path(__file__).resolve().parent / "output" / "qc_failed.jsonl"
DEFAULT_ENV = PROJECT_ROOT / ".env"

# 平假名 + 片假名（含半角片假名）残留检测
KANA_RE = re.compile(r"[぀-ゟ゠-ヿｦ-ﾟ]")

SYSTEM_PROMPT = """你是资深的日系 galgame 汉化组翻译。把用户给定的日文游戏台词与上下文翻译成简体中文。

硬性要求：
1. galgame 汉化腔：口语化、生动、有二次元味道，禁止翻译腔长句；保留并自然转化语气词（哈啊、呢、哦、嘛、啦、的说、才不是……等）。
2. 人名、自称、口癖、称呼严格按 glossary 对照表，不得自创译名；glossary 未覆盖的专有名词用自然的中文音译/意译。
3. 保留原文的标点节奏（……、！、？、　分隔），脏话/吐槽的力度不弱化。
4. 「地」是旁白标记，其文本是叙事句，翻成中文叙述，不要加引号。
5. 一次请求会给出一条目标台词（target）和它的邻接上下文（context，按时间顺序排列，前半是前文、后半是后文）。context 仅用于理解语气与指代，但你必须同时给出 context 每条的中文译文，保持人物语气一致。
6. 只输出 JSON，不要输出任何解释。输出结构：
{"text": "<target 的中文译文>", "context": [{"id": "<原样保留>", "text": "<中文译文>"}, ...]}
"""


# ---------------------------------------------------------------- 配置加载
def load_dotenv_manual(env_path: Path) -> dict:
    """手写 key=value 解析，不依赖 python-dotenv。文件不存在返回 {}。"""
    cfg = {}
    if not env_path.is_file():
        return cfg
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k:
            cfg[k] = v
    return cfg


def resolve_config(args) -> dict:
    file_cfg = load_dotenv_manual(Path(args.env))
    get = lambda k: os.environ.get(k) or file_cfg.get(k) or ""
    cfg = {
        "api_key": get("API_KEY"),
        "api_base": get("API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": args.model or get("MODEL") or "deepseek-v3.2",
    }
    if not cfg["api_key"] and not args.mock:
        sys.exit(
            "错误：未找到 API_KEY（项目根 .env 不存在或未配置，环境变量也没有）。\n"
            "请复制 .env.example 为 .env 并填入百炼 API-KEY，或使用 --mock 做离线验证。"
        )
    return cfg


# ---------------------------------------------------------------- 翻译核心
def build_user_prompt(record: dict, glossary_entries: list) -> str:
    payload = {
        "glossary": [{"src": g["src"], "dst": g["dst"], "note": g.get("note", "")} for g in glossary_entries],
        "target": {
            "id": record["id"],
            "speaker": record["speaker"],
            "character": record["character"],
            "text": record["text"],
        },
        "context": [
            {"id": c.get("id"), "speaker": c.get("speaker") or "地", "text": c.get("text") or ""}
            for c in (record.get("context") or [])
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def mock_translate(record: dict) -> dict:
    """离线占位：直接返回日文原文，结构与时序与真实调用一致。"""
    time.sleep(0.01)  # 模拟一点点耗时，验证并发写入不串行
    return {
        "text": record["text"],
        "context": [{"id": c.get("id"), "text": c.get("text") or ""} for c in (record.get("context") or [])],
    }


def api_translate(client, model: str, record: dict, glossary_entries: list,
                  max_retries: int, base_delay: float) -> dict:
    """调用 OpenAI 兼容接口，429/5xx/连接错误指数退避重试。"""
    from openai import APIConnectionError, APIStatusError  # 延迟导入，mock 不需要

    user_prompt = build_user_prompt(record, glossary_entries)
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            if not isinstance(data.get("text"), str) or not data["text"].strip():
                raise ValueError("返回 JSON 缺少非空 text 字段")
            ctx = data.get("context") or []
            if not isinstance(ctx, list):
                raise ValueError("context 字段不是数组")
            return {"text": data["text"], "context": ctx}
        except APIStatusError as e:  # 429 / 5xx 退避
            last_err = e
            status = getattr(e, "status_code", None)
            retriable = status == 429 or (isinstance(status, int) and status >= 500)
            if not retriable or attempt >= max_retries:
                raise
        except (APIConnectionError, json.JSONDecodeError, ValueError) as e:
            last_err = e
            if attempt >= max_retries:
                raise
        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
        time.sleep(delay)
    raise last_err  # pragma: no cover


def qc_check(translation: dict) -> list:
    """返回残留日文字符清单；空列表表示通过。"""
    hits = []
    for m in KANA_RE.finditer(translation.get("text") or ""):
        hits.append(m.group(0))
    for c in translation.get("context") or []:
        for m in KANA_RE.finditer(str(c.get("text") or "")):
            hits.append(m.group(0))
    return hits


# ---------------------------------------------------------------- 主流程
def load_done_ids(path: Path) -> set:
    done = set()
    if path.is_file():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return done


def main() -> int:
    ap = argparse.ArgumentParser(
        description="日文 galgame 台词 → 中文翻译管线（OpenAI 兼容接口，支持 mock/断点续跑）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--input", default=str(DEFAULT_INPUT), help="输入 dialogue_examples.jsonl")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="主输出 jsonl（追加写，断点续跑）")
    ap.add_argument("--qc-failed", default=str(DEFAULT_QC_FAILED), help="质检失败记录输出")
    ap.add_argument("--glossary", default=str(DEFAULT_GLOSSARY), help="glossary.json 路径")
    ap.add_argument("--env", default=str(DEFAULT_ENV), help=".env 路径（手写 key=value 解析）")
    ap.add_argument("--model", default=None, help="覆盖 .env 里的 MODEL")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 条未完成的记录（测试用）")
    ap.add_argument("--workers", type=int, default=4, help="并发线程数")
    ap.add_argument("--max-retries", type=int, default=5, help="429/5xx 最大重试次数")
    ap.add_argument("--base-delay", type=float, default=2.0, help="退避基数秒（指数增长）")
    ap.add_argument("--mock", action="store_true", help="不调用 API，日文原文当中文占位输出")
    args = ap.parse_args()

    cfg = resolve_config(args)
    input_path, output_path = Path(args.input), Path(args.output)
    qc_path = Path(args.qc_failed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    qc_path.parent.mkdir(parents=True, exist_ok=True)

    glossary = json.loads(Path(args.glossary).read_text(encoding="utf-8"))
    glossary_entries = glossary["entries"]
    speaker_map = glossary.get("speaker_map", {})

    records = []
    with input_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    done_ids = load_done_ids(output_path)
    todo = [r for r in records if r["id"] not in done_ids]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"[translate] 总记录 {len(records)}，已完成 {len(done_ids)}，本次待翻 {len(todo)}"
          f"（mode={'MOCK' if args.mock else 'API:' + cfg['model']}, workers={args.workers}）")
    if not todo:
        print("[translate] 没有待处理记录，退出。")
        return 0

    client = None
    if not args.mock:
        from openai import OpenAI
        client = OpenAI(api_key=cfg["api_key"], base_url=cfg["api_base"])  # key 绝不打印

    write_lock = threading.Lock()
    stats = {"ok": 0, "qc_failed": 0, "error": 0}
    t0 = time.time()

    def work(record):
        if args.mock:
            tr = mock_translate(record)
        else:
            tr = api_translate(client, cfg["model"], record, glossary_entries,
                               args.max_retries, args.base_delay)
        out = {
            "id": record["id"],
            "character": record["character"],
            "speaker": record["speaker"],
            "speaker_zh": speaker_map.get(record["speaker"], record["speaker"]),
            "source_file": record.get("source_file"),
            "sequence": record.get("sequence"),
            "text_src": record["text"],
            "text_zh": tr["text"],
            "context_zh": [
                {
                    "id": c.get("id"),
                    "speaker": c.get("speaker"),
                    "speaker_zh": speaker_map.get(c.get("speaker") or "地", c.get("speaker") or "地"),
                    "text": c.get("text") or "",
                }
                for c in (record.get("context") or [])
            ],
        }
        # 用译文覆盖 context_zh 文本（按 id 对齐；对不上号的保留原文，交给 QC 抓）
        tr_ctx = {str(c.get("id")): c.get("text") for c in (tr.get("context") or [])}
        for c in out["context_zh"]:
            if str(c["id"]) in tr_ctx and isinstance(tr_ctx[str(c["id"])], str):
                c["text"] = tr_ctx[str(c["id"])]
        if args.mock:
            out["mock"] = True
        kana_hits = qc_check({"text": out["text_zh"], "context": out["context_zh"]})
        return out, kana_hits

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, r): r for r in todo}
        for fut in as_completed(futures):
            record = futures[fut]
            try:
                out, kana_hits = fut.result()
            except Exception as e:  # 单条失败不拖垮全局，记入 qc_failed
                with write_lock:
                    stats["error"] += 1
                    with qc_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "id": record["id"], "character": record.get("character"),
                            "text_src": record.get("text"),
                            "qc_reason": f"translate_error: {type(e).__name__}: {e}",
                        }, ensure_ascii=False) + "\n")
                print(f"[error] {record['id']}: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            with write_lock:
                if kana_hits and not args.mock:
                    stats["qc_failed"] += 1
                    out["qc_reason"] = f"残留日文假名: {''.join(sorted(set(kana_hits)))}"
                    with qc_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(out, ensure_ascii=False) + "\n")
                else:
                    stats["ok"] += 1
                    if kana_hits:  # mock 模式占位输出必然含假名，只提示不剔除
                        out["qc_note"] = "mock 占位输出，跳过假名剔除"
                    with output_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(out, ensure_ascii=False) + "\n")
                done = stats["ok"] + stats["qc_failed"] + stats["error"]
                if done % 50 == 0 or done == len(todo):
                    rate = done / max(time.time() - t0, 1e-6)
                    print(f"[progress] {done}/{len(todo)}  ok={stats['ok']} "
                          f"qc_failed={stats['qc_failed']} error={stats['error']}  {rate:.1f}/s")

    print(f"[done] ok={stats['ok']} qc_failed={stats['qc_failed']} error={stats['error']} "
          f"耗时 {time.time() - t0:.1f}s → {output_path}")
    return 0 if stats["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
