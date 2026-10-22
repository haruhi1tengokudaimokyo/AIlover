# 麦的独立 LLM 管线

默认执行 `finetune_data/mugi/build_llm.py` 只离线构建，不调用 API。
源数据为 `source/dialogue_examples.jsonl`；目标样本及上下文都保留原文 ID 与来源信息。
上下文仅含同一脚本分段内的前文，避免把目标回复或之后的台词放进训练输入。

## 已有产物

- `glossary.json`：从原词典复制，独立修正麦的名字和称呼。
- `output/seed_samples.json`：5 条自然中文卡片改写，标准 JSON 数组。
- `output/sharegpt.json`：真实译稿转换结果，未开始翻译时为空数组 `[]`。
- `output/dataset_info.json`：只注册实际有内容的文件，种子项为 `ousama_mugi_seed`；中文语料非空后才注册 `ousama_mugi_corpus`。
- `build_summary.json`：可核查的来源数量、种子数量、译稿接受/拒绝数量和翻译状态。

## 在用户自行配置翻译 API 后执行

在项目根 `.env` 中填 `API_KEY`、`API_BASE` 和 `MODEL`（与原翻译管线约定一致，不写进数据包）。
下列 `--translate` 会调用真实外部翻译服务，产生该服务的费用；本轮没有执行这些命令。

```powershell
# 先试 20 条；同一独立输出目录支持续跑
.venv/Scripts/python.exe finetune_data/mugi/build_llm.py --translate --limit 20

# 审阅 output/translated.jsonl 与 output/qc_failed.jsonl 后继续全量
.venv/Scripts/python.exe finetune_data/mugi/build_llm.py --translate

# 不联网，只根据当前真实译稿重建训练 JSON
.venv/Scripts/python.exe finetune_data/mugi/build_llm.py
```

翻译调用原有 `finetune_data/llm/translate_corpus.py`，显式传入麦的独立 input/output/qc/glossary 路径；
不会覆盖原两位的翻译或 ShareGPT。可用 `--workers`、`--model` 调整翻译参数。
`--translated-input <path>` 可离线导入经审阅的同结构译稿。

## 转换时的保护

- 拒绝任何 `mock=true`、`qc_note`、`qc_reason` 的占位/失败记录。
- 拒绝残留日文假名、空译文、目标原文未改变、未知来源 ID、角色或源文件/原文不匹配。
- 译文 context 的 ID 顺序必须与安全前文完全对应，不能混入目标或未来台词。
- 重复 ID 不重复入样本；接受和拒绝计数写入 `build_summary.json`。
- 从 system 中移除卡片示例段，示例分别作为训练样本，保留“中文改写而非原文翻译”的标注。

训练时将有内容的 JSON 和其 `dataset_info.json` 独立项导入 LLaMA-Factory。
不要将空语料、旧的 mock 产物，或仅 5 条种子当作已完成全量微调。
