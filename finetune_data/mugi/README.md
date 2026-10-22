# 麦（むぎ / mugi）的独立微调准备包

本包复用绯华、菖蒲的提取和微调准备方法，为游戏里的第一位女仆麦补齐材料。
原两位的清洗数据、音频、翻译脚本、ShareGPT 构建脚本与已有产物保持原样。

## 已完成的材料

- `extracted/characters/mugi/`：重新解析原游戏脚本后的原始台词、来源位置与哈希、干净台词、称呼/自称/语尾统计、120 条抽样和 60 条参考候选。
- `extracted/voice/vo1_*.opus`：麦的原始声音。提取只新增 `vo1_`，不改其他角色的音频。
- `tts/dataset/mugi/`：复用原 TTS 构建器转成 32 kHz / 单声道 / 16-bit PCM。
- `tts/mugi.list`：使用原 `DATASET_ROOT` 占位约定的 GPT-SoVITS 日文标注，时长限定 2–15 秒。
- `tts/reference/`：三条完整日常台词参考 WAV 与同名日文文本，5–10 秒，文本与 RMS/峰值已检查。
- `backend/seed_assets/mugi/voice_ref.opus` / `.txt`：与第一条 WAV 参考对应的原始 Opus 和文本，附来源哈希文件。
- `llm/source/dialogue_examples.jsonl`：完整可用的日文风格语料；包含来源 ID、文件、行号、哈希和**仅前文**的同分段上下文。
- `llm/glossary.json`：独立词典，统一「むぎ→麦」「むぎちゃん→麦酱」「ご主人様→主人」，不改原词典。
- `llm/output/seed_samples.json`：来自麦角色卡的 5 条中文改写示例；是语感示例，不是游戏原文翻译或剧情证据。
- `llm/output/dataset_info.json`：独立 `ousama_mugi_seed` 注册项。真实译稿通过后再生成 `ousama_mugi_corpus`，不与原注册项撞名。

最终数量见 [来源统计](source_summary.json)、[TTS 质检](tts/qa_report.md) 与 [LLM 状态](llm/build_summary.json)。

## 原始数量为何与旧 corpus 不同

旧 `extracted/corpus.jsonl` 缺少逐行来源。这里从实际 `.ks` 脚本重新解析，不覆盖旧 corpus。
保守解析器在未知控制、标签和分支边界重置说话人，不能确定归属的行不会硬算给麦。
日文 raw 记录保留以供复查；训练数据复用旧过滤，再额外排除明确的 `H_Start` 场景、纯喘息和睡声。
不能只按音量排序挑参考：本包最终固定选取敲门、第一号女仆自我介绍、便利店便当三个日常句子。

## 重建

在项目根目录执行：

```powershell
.venv/Scripts/python.exe scripts/prepare_mugi_training.py
.venv/Scripts/python.exe scripts/test_mugi_training.py
.venv/Scripts/python.exe scripts/verify_mugi_training.py
```

该命令只操作麦的独立输出；不执行训练、不调用任何外部模型或声音克隆服务。
已有源音频会验证后复用。可用 `--skip-source` / `--skip-tts` / `--skip-llm` 跳过阶段。
`tts/README.md` 包含训练标注和参考的路径填写方式。
重复清洗时加 `--reuse-audio` 可逐一校验先前提取哈希并复用，避免重新读取大档索引。
每次重建后运行 `verify_mugi_training.py`，刷新 `verification.json`，核对全部标注 WAV、
三条参考的来源、LLM 源/清洗 ID 集合，并在本机旧数据基线存在时重核旧两位文件的哈希。
这份报告是运行时验收快照，不应在重建后沿用旧数值；高峰值记录会标记数量，尚未人工逐条试听。

## 全量中文翻译与训练状态

**全量中文翻译尚未执行，模型尚未训练，也没有完成麦的克隆音色。**
这与前两位原本准备状态一致：先完成日文语料、TTS 数据、中文角色卡示例和翻译入口。
已提供可运行的真实翻译/续跑/质检入口，见 [LLM 操作说明](llm/README.md)。
离线输出中的 `sharegpt.json` 当前为空数组，不会把日文占位数据伪装成中文训练样本。
5 条人工改写示例仅用来起步和检查格式，不应当作足够的全量微调训练集。

原始游戏文本、图、声音和生成数据仅保留在本机；Git 中只保留工具与必要说明/无原文统计。
