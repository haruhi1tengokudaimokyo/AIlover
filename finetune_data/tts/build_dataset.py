# -*- coding: utf-8 -*-
"""
GPT-SoVITS 微调数据集构建脚本（AI 伴侣项目）

功能：
  1. 逐角色读取 lines_clean.jsonl（{"text","voice","file"}）
  2. opus -> wav 转码（32kHz / 单声道 / s16 PCM），8 线程并行
  3. 质检：时长 <min 或 >max、文件损坏/过小、text 为空、voice 缺失
  4. 生成 GPT-SoVITS 标注文件 <char>.list（DATASET_ROOT 字面占位符）
  5. 每角色挑 3 条 5-10s、音量正常的参考音频到 reference/
  6. 输出 qa_report.md 与 README.md

用法（Git Bash）：
  /d/AIlover/.venv/Scripts/python.exe finetune_data/tts/build_dataset.py \
      --project-root /d/AIlover \
      --out-dir finetune_data/tts \
      --char hika=extracted/characters/hika/lines_clean.jsonl \
      --char ayame=extracted/characters/ayame/lines_clean.jsonl

重跑安全：所有输出先删后建（仅限 out-dir 内本次产物），可重复执行。
"""
from __future__ import annotations

import argparse
import audioop  # Python 3.12 仍内置（3.13 移除），C 实现，快
import json
import shutil
import statistics
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG = "ffmpeg"  # fallback：要求系统 PATH 里有 ffmpeg

MIN_DUR_DEFAULT = 2.0
MAX_DUR_DEFAULT = 15.0
REF_MIN_DUR, REF_MAX_DUR = 5.0, 10.0
MIN_WAV_BYTES = 1024          # wav 文件小于该值视为损坏
RMS_QUIET = 800               # 16-bit PCM RMS 低于此值视为过轻
CLIP_PEAK_RATIO = 0.98        # 峰值超过满幅的 98% 视为可能削波
SILENCE_RMS = 100             # 验收用：低于此值视为静音

HEADER = Path(__file__).resolve().parent.parent.parent  # 仅用于推导默认项目根


def log(msg: str) -> None:
    print(msg, flush=True)


def clean_text(text: str) -> str:
    """清洗 .list 里的文本：去掉换行、竖线，压缩空白。"""
    t = (text or "").replace("|", " ").replace("\r", " ").replace("\n", " ")
    return " ".join(t.split()).strip()


def convert_one(ffmpeg: str, src: Path, dst: Path) -> tuple[bool, str]:
    """ffmpeg opus -> wav 32k mono s16。返回 (成功, 错误信息)。"""
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), "-ar", "32000", "-ac", "1", "-sample_fmt", "s16", str(dst)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return False, (r.stderr or "ffmpeg failed").strip()[:200]
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def wav_info(path: Path) -> tuple[float, float, float, int]:
    """用 wave 模块读取 wav：返回 (时长秒, RMS, 峰值比例, 帧率)。读不了则抛异常。"""
    with wave.open(str(path), "rb") as w:
        fr = w.getframerate()
        n = w.getnframes()
        sw = w.getsampwidth()
        ch = w.getnchannels()
        frames = w.readframes(n)
    if sw != 2:
        raise ValueError(f"unexpected sample width {sw}")
    if not frames:
        return 0.0, 0.0, 0.0, fr
    rms = audioop.rms(frames, sw)
    peak = audioop.max(frames, sw)
    dur = n / fr if fr else 0.0
    return dur, float(rms), peak / 32768.0, fr


def process_character(name: str, jsonl: Path, project_root: Path, out_dir: Path,
                      ffmpeg: str, workers: int, min_dur: float, max_dur: float) -> dict:
    """处理单个角色：转码 -> 质检 -> 返回统计与通过条目。"""
    ds_dir = out_dir / "dataset" / name
    ds_dir.mkdir(parents=True, exist_ok=True)

    records = []
    with jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    log(f"[{name}] 读入 {len(records)} 条记录")

    # ---- 转码（并行）----
    jobs = []          # (record, src, dst)
    missing_voice = []  # voice 文件缺失的记录
    for rec in records:
        voice_rel = rec.get("voice") or ""
        src = project_root / voice_rel
        dst = ds_dir / (Path(voice_rel).stem + ".wav")
        if not voice_rel or not src.is_file():
            missing_voice.append(rec)
        else:
            jobs.append((rec, src, dst))

    convert_fail = []  # (record, err)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(convert_one, ffmpeg, src, dst): (rec, dst) for rec, src, dst in jobs}
        for fut in as_completed(futs):
            rec, dst = futs[fut]
            ok, err = fut.result()
            if not ok:
                convert_fail.append((rec, err))
                dst.unlink(missing_ok=True)
            done += 1
            if done % 200 == 0 or done == len(futs):
                log(f"[{name}] 转码进度 {done}/{len(futs)}")

    # ---- 质检（串行，wave 模块）----
    passed = []            # {"wav": Path, "text": str, "dur": float, "rms": float, "peak": float}
    excluded = {           # 原因 -> 记录列表
        "voice_missing": missing_voice,
        "convert_fail": [r for r, _ in convert_fail],
        "empty_text": [],
        "wav_unreadable_or_small": [],
        "duration_out_of_range": [],
    }
    for rec, _, dst in jobs:
        if any(rec is r for r, _ in convert_fail):
            continue  # 已计入 convert_fail
        text = clean_text(rec.get("text", ""))
        if not text:
            excluded["empty_text"].append(rec)
            continue
        try:
            if not dst.is_file() or dst.stat().st_size < MIN_WAV_BYTES:
                raise ValueError("wav missing or too small")
            dur, rms, peak, fr = wav_info(dst)
            if fr != 32000:
                raise ValueError(f"framerate {fr}")
        except Exception:  # noqa: BLE001
            excluded["wav_unreadable_or_small"].append(rec)
            dst.unlink(missing_ok=True)
            continue
        if dur < min_dur or dur > max_dur:
            excluded["duration_out_of_range"].append(rec)
            continue
        passed.append({"wav": dst, "text": text, "dur": dur, "rms": rms, "peak": peak,
                       "stem": dst.stem})

    return {"name": name, "total": len(records), "passed": passed, "excluded": excluded}


def pick_references(passed: list[dict]) -> tuple[list[dict], list[str]]:
    """挑 3 条 5-10s、音量正常（不过轻、不削波）的参考音频。"""
    cand = [p for p in passed
            if REF_MIN_DUR <= p["dur"] <= REF_MAX_DUR
            and p["rms"] >= RMS_QUIET
            and p["peak"] < CLIP_PEAK_RATIO]
    # 优先选 RMS 接近 2500（典型正常语音响度）的，拉开文件来源
    cand.sort(key=lambda p: abs(p["rms"] - 2500))
    picked, used_prefix = [], set()
    for p in cand:
        prefix = p["stem"].split("_")[0]
        if prefix in used_prefix and len(picked) < 3:
            continue
        picked.append(p)
        used_prefix.add(prefix)
        if len(picked) == 3:
            break
    for p in cand:  # 不够 3 条则放宽前缀限制补齐
        if len(picked) >= 3:
            break
        if p not in picked:
            picked.append(p)
    notes = []
    if len(picked) < 3:
        notes.append(f"参考音频候选不足，仅选出 {len(picked)} 条")
    return picked[:3], notes


def fmt_h(seconds: float) -> str:
    return f"{seconds / 3600:.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build GPT-SoVITS dataset from galgame lines")
    ap.add_argument("--project-root", default=str(HEADER), help="项目根目录（voice 相对路径基于此）")
    ap.add_argument("--out-dir", default="finetune_data/tts", help="输出目录（相对项目根或绝对路径）")
    ap.add_argument("--char", action="append", required=True,
                    help="角色定义，形如 hika=extracted/characters/hika/lines_clean.jsonl，可多次")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-dur", type=float, default=MIN_DUR_DEFAULT)
    ap.add_argument("--max-dur", type=float, default=MAX_DUR_DEFAULT)
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve()
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = project_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reference").mkdir(parents=True, exist_ok=True)
    log(f"ffmpeg: {FFMPEG}")
    log(f"project_root: {project_root}\nout_dir: {out_dir}")

    chars = []
    for c in args.char:
        name, _, rel = c.partition("=")
        chars.append((name.strip(), project_root / rel.strip()))

    results = []
    for name, jsonl in chars:
        results.append(process_character(name, jsonl, project_root, out_dir, FFMPEG,
                                         args.workers, args.min_dur, args.max_dur))

    # ---- 写 .list（DATASET_ROOT 字面占位符）----
    for res in results:
        list_path = out_dir / f"{res['name']}.list"
        with list_path.open("w", encoding="utf-8") as f:
            for p in res["passed"]:
                f.write(f"DATASET_ROOT/{res['name']}/{p['wav'].name}|{res['name']}|ja|{p['text']}\n")
        log(f"[{res['name']}] 写出 {list_path.name}：{len(res['passed'])} 行")

    # ---- 参考音频 ----
    ref_info = {}
    for res in results:
        picked, notes = pick_references(res["passed"])
        ref_info[res["name"]] = (picked, notes)
        for i, p in enumerate(picked, 1):
            dst = out_dir / "reference" / f"{res['name']}_ref_{i}.wav"
            shutil.copy2(p["wav"], dst)
            dst.with_suffix(".txt").write_text(p["text"], encoding="utf-8")
            log(f"[{res['name']}] 参考音频 {dst.name} <- {p['wav'].name} "
                f"({p['dur']:.2f}s, RMS={p['rms']:.0f}, peak={p['peak']:.2f})")

    # ---- qa_report.md ----
    lines = ["# GPT-SoVITS 数据集质检报告", ""]
    lines.append(f"- 转码参数：32kHz / 单声道 / 16-bit PCM；质检时长区间 [{args.min_dur}, {args.max_dur}] 秒")
    lines.append(f"- 参考音频筛选：{REF_MIN_DUR}-{REF_MAX_DUR} 秒，RMS ≥ {RMS_QUIET}，峰值 < {CLIP_PEAK_RATIO} 满幅")
    lines.append("")
    grand_pass = 0
    grand_sec = 0.0
    for res in results:
        name, total, passed, excluded = res["name"], res["total"], res["passed"], res["excluded"]
        durs = [p["dur"] for p in passed]
        n_ex = sum(len(v) for v in excluded.values())
        grand_pass += len(passed)
        grand_sec += sum(durs)
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- 总记录数：{total}")
        lines.append(f"- 质检通过（进入 .list）：{len(passed)}")
        lines.append(f"- 排除合计：{n_ex}")
        for k, v in excluded.items():
            if v:
                lines.append(f"  - {k}：{len(v)}")
        if durs:
            lines.append(f"- 时长分布（秒）：min={min(durs):.2f}，中位={statistics.median(durs):.2f}，"
                         f"mean={statistics.mean(durs):.2f}，max={max(durs):.2f}")
            lines.append(f"- 合计时长：{fmt_h(sum(durs))} 小时（{sum(durs):.0f} 秒）")
        picked, notes = ref_info[name]
        lines.append(f"- 参考音频：{len(picked)} 条")
        for i, p in enumerate(picked, 1):
            lines.append(f"  - reference/{name}_ref_{i}.wav <- dataset/{name}/{p['wav'].name} "
                         f"（{p['dur']:.2f}s，RMS={p['rms']:.0f}，peak={p['peak']:.2f}）：{p['text']}")
        for nt in notes:
            lines.append(f"  - ⚠️ {nt}")
        lines.append("")
    lines.append("## 合计")
    lines.append("")
    lines.append(f"- 通过总条数：{grand_pass}")
    lines.append(f"- 总时长：{fmt_h(grand_sec)} 小时")
    lines.append("")
    (out_dir / "qa_report.md").write_text("\n".join(lines), encoding="utf-8")
    log("写出 qa_report.md")

    # ---- README.md ----
    char_names = "、".join(n for n, _ in chars)
    readme = f"""# GPT-SoVITS 微调数据集（{char_names}）

## 目录结构

```
finetune_data/tts/
├── build_dataset.py        # 本数据集的构建脚本（可重跑，参数见文件头注释）
├── dataset/
│   ├── hika/               # 佐藤绯华 wav（32kHz 单声道 s16）
│   └── ayame/              # 藤丘菖蒲 wav
├── hika.list               # GPT-SoVITS 标注文件（DATASET_ROOT 占位符）
├── ayame.list
├── reference/              # 每角色 3 条参考音频 + 同名 .txt 台词
│   ├── hika_ref_1.wav / .txt ...
│   └── ayame_ref_1.wav / .txt ...
├── qa_report.md            # 质检报告
└── README.md
```

## .list 格式

每行：`DATASET_ROOT/<char>/<name>.wav|<char>|ja|台词文本`
`DATASET_ROOT` 是字面占位符，**不要**在本地替换；上传到云端后用下面的 sed 一次性修正。

## 上传到 AutoDL 后

假设数据集放在云端 `~/GPT-SoVITS/data/tts/`（即 dataset/ 的上层）：

```bash
cd ~/GPT-SoVITS/data/tts
sed -i 's|DATASET_ROOT|/root/GPT-SoVITS/data/tts/dataset|g' hika.list ayame.list
# 验证：第一行指向的文件确实存在
head -1 hika.list | cut -d'|' -f1 | xargs ls -l
```

注意 sed 分隔符用 `|` 以外的字符会撞路径里的 `/`，上面直接用 `|` 做分隔符是因为 .list 里
路径字段本身不含 `|`，而替换目标 `/root/...` 不含 `|`。若目标路径里含 `|` 请换 `#`。

## GPT-SoVITS WebUI 填写

1. **标注/训练语种选 `ja`（日文）**：素材为 galgame 日文语音，.list 第 3 字段已写 `ja`。
2. **文本标注文件路径**：填修正后的 hika.list / ayame.list 绝对路径（两个角色建议分开训练两个模型，
   也可合并成一个 list 训练单模型后用参考音频区分音色，但分离训练效果更稳）。
3. **推理时切语种**：推理文本若是中文，输入语种选 `zh`，并勾选/保持「参考音频语种 ja」的
   跨语种推理（GPT-SoVITS v2 支持中日英混合，前端会自动分句）。
4. **参考音频**：推理页面上传 `reference/<char>_ref_*.wav`，并把同名 `.txt` 里的日文台词
   粘进参考文本框，参考音频语种选 `ja`。
5. 训练集较小（见 qa_report.md 合计时长），建议 batch size 调小、epochs 10-15 起步观察过拟合。

## 备注

- `dataset/<char>/` 目录里保留了少量**时长越界（<2s 或 >15s）的 wav**，它们不在 .list 里、不参与训练；
  如需精简体积可按 .list 反选删除。
- hika 源数据中有 5 个 voice 文件各被 2 条台词共用（vo2_0320/0321/0324/0325/0326），
  表现为 .list 里不同文本指向同一 wav，属正常现象。
- 另有 voice 字段为 null 的记录（hika 34、ayame 19），已按 voice_missing 排除。

## 重跑

在项目根目录、激活 `.venv` 后执行（Windows Python 请用 Windows 风格路径）：

```bash
python finetune_data/tts/build_dataset.py --project-root . \
    --char hika=extracted/characters/hika/lines_clean.jsonl \
    --char ayame=extracted/characters/ayame/lines_clean.jsonl
```
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    log("写出 README.md")

    # ---- 验收自检 ----
    log("\n==== 自检 ====")
    ok_all = True
    for res in results:
        name = res["name"]
        list_path = out_dir / f"{name}.list"
        n_lines = sum(1 for _ in list_path.open("r", encoding="utf-8"))
        match = n_lines == len(res["passed"])
        ok_all &= match
        log(f"[{name}] .list 行数 {n_lines} == 通过数 {len(res['passed'])}: {'OK' if match else 'FAIL'}")
        first = list_path.open("r", encoding="utf-8").readline().strip()
        if first.startswith("DATASET_ROOT/"):
            rel_wav = first.split("|", 1)[0].replace("DATASET_ROOT", "dataset")
            exists = (out_dir / rel_wav).is_file()
            ok_all &= exists
            log(f"[{name}] 首行 wav 存在: {'OK' if exists else 'FAIL'} ({rel_wav})")
        else:
            ok_all = False
            log(f"[{name}] 首行未用 DATASET_ROOT 占位符: FAIL")
        # 抽查 3 个 wav
        import random
        random.seed(42)
        for p in random.sample(res["passed"], min(3, len(res["passed"]))):
            try:
                dur, rms, peak, fr = wav_info(p["wav"])
                good = fr == 32000 and abs(dur - p["dur"]) < 0.05 and rms > SILENCE_RMS
                ok_all &= good
                log(f"[{name}] 抽查 {p['wav'].name}: fr={fr}, dur={dur:.2f}s, RMS={rms:.0f} "
                    f"{'OK' if good else 'FAIL'}")
            except Exception as e:  # noqa: BLE001
                ok_all = False
                log(f"[{name}] 抽查 {p['wav'].name}: FAIL {e}")
    log(f"\n自检总体: {'ALL OK' if ok_all else 'HAS FAILURES'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
