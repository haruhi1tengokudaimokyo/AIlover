# LLM 角色微调数据管线（finetune_data/llm/）

从日文 galgame 台词语料（3272 条：绯华 1960 / 菖蒲 1312）产出**全中文** sharegpt 训练数据，
用于 Qwen2.5-7B-Instruct + LLaMA-Factory LoRA 微调。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `translate_corpus.py` | 日→中翻译管线：断点续跑、4 线程并发、429/5xx 退避重试、假名残留质检、`--mock` 离线验证 |
| `glossary.json` | 角色词典：`entries`（注入翻译 prompt 的日→中对照）+ `speaker_map`（说话人名映射，肇→你、地→旁白） |
| `build_sharegpt.py` | 翻译结果 + 角色卡示例 → LLaMA-Factory sharegpt 格式，附 `dataset_info.json` |
| `output/translated.jsonl` | 翻译主输出（追加写，断点续跑依据） |
| `output/qc_failed.jsonl` | 质检失败/翻译报错记录（从主输出剔除，可人工修复后回填） |
| `output/sharegpt.json` | 语料样本：`{"conversations":[human, gpt], "system": 角色人设}` |
| `output/seed_samples.json` | 角色卡 5 组手写示例 × 2 角色 = 10 条样本（零翻译成本） |
| `output/dataset_info.json` | LLaMA-Factory 数据集注册片段（`ousama_corpus` / `ousama_seed`） |

## 拿到 API key 后的操作步骤

```bash
cd /d/AIlover

# 1. 配置 key（脚本手写解析 key=value，不依赖 python-dotenv；绝不打印 key）
cp .env.example .env        # 填入 API_KEY=sk-...（百炼控制台获取）
                            # API_BASE / MODEL=deepseek-v3.2 已有默认值

# 2. 删除 mock 验证产生的占位输出（重要！断点续跑会跳过已有 id）
rm -f finetune_data/llm/output/translated.jsonl finetune_data/llm/output/qc_failed.jsonl

# 3. 小规模试跑 20 条，检查 output/translated.jsonl 译文风格
python finetune_data/llm/translate_corpus.py --limit 20

# 4. 满意后全量跑 3272 条（中断后重跑同一命令即可续跑）
python finetune_data/llm/translate_corpus.py

# 5. 检查质检失败记录
wc -l finetune_data/llm/output/qc_failed.jsonl
#    失败原因有两类：残留日文假名（译文里混了假名）、translate_error（重试耗尽）。
#    简单处理：删掉 qc_failed.jsonl 里对应 id 在主输出中不存在，直接重跑步骤 4 会自动补翻这些 id。

# 6. 生成 sharegpt 训练数据
python finetune_data/llm/build_sharegpt.py

# 7. 上传 AutoDL（在 AutoDL 实例上部署 LLaMA-Factory 后）
#    把 output/sharegpt.json、output/seed_samples.json 上传到实例的
#    LLaMA-Factory/data/ 目录，并把 output/dataset_info.json 的内容
#    合并进 LLaMA-Factory/data/dataset_info.json（追加两个键即可）。
```

## 成本与耗时预估（deepseek-v3.2，估算量级）

- 语料规模：3272 条，正文+上下文共约 38.5 万日文字符。
- 每条一次请求：输入 ≈ 系统 prompt（约 300 tok）+ glossary（约 700 tok）+ 记录内容（平均约 120 字），
  全量输入约 **400 万 tokens**；输出约 **80 万 tokens**。
- 按百炼 deepseek-v3.2 输入约 ¥2/百万、输出约 ¥8/百万估算：**总成本约 ¥10–20 元人民币**（以控制台实际单价为准）。
- 耗时：4 线程并发、单条约 2–4 秒，全量约 **30–60 分钟**。

## LLaMA-Factory WebUI 配置建议

| 项目 | 值 |
| --- | --- |
| 基座模型 | `Qwen2.5-7B-Instruct` |
| 微调方式 | LoRA（`lora_rank=16`, `lora_alpha=32`, `lora_dropout=0.05`，target 选 `all`） |
| 训练阶段 | Supervised Fine-Tuning（sft） |
| 数据集 | 勾选 `ousama_corpus` + `ousama_seed`（dataset_info.json 已注册为 sharegpt 格式） |
| 模板 template | `qwen` |
| cutoff_len | 2048（人设 system 较长，勿低于 1024） |
| 学习率 | `1e-4`（cosine，warmup_ratio 0.03） |
| epochs | 2–3（语料约 3.3k 条，先 2 epoch 看效果） |
| batch | per_device 2 × grad_accum 8（显存紧张开 gradient_checkpointing 或换 4bit QLoRA） |
| 精度 | bf16 |

训练后把 LoRA 权重导出（WebUI 的 Export 面板合并），接回项目的聊天后端即可。

## 数据 schema 备忘（探查实测）

- `dialogue_examples.jsonl` 每条字段：`id / speaker / character(hika|ayame) / text / sequence / source_file / context / ...`；
  全部 3272 条 `evidence_type=style`，`text` 无空值。
- **`context` 最多 4 条**（前 2 条 + 后 2 条邻接上下文，按时间顺序排列），字段只有
  `id / speaker / text / evidence_type`，**没有位置标记**，顺序即先后。
- 3272 条中 9 条无上下文 → `build_sharegpt.py` 转成单轮样本，human 用贴合场景的开场
  （绯华：「你就是新来的女仆？」；菖蒲：「你就是菖蒲？绯华经常提起你。」）。
- 22 条 context 的 `speaker` 为 `null`，按旁白处理。
- 上下文说话人共 12 种：肇（男主/用户）、緋華、菖蒲、地（旁白）、むぎ（小麦）、伊知花、
  黒依、凛々、焔花、小唄、アンジェ、来葉 —— 已全部收入 `glossary.json` 的 `speaker_map`。

## mock 模式说明

`--mock` 不调用 API（零网络依赖），把日文原文当中文占位输出，用于验证管线（并发写入、
断点续跑、格式转换）。mock 输出必然含假名，此时**质检只标注 `qc_note` 不剔除**；
正式运行时残留假名的记录会写入 `qc_failed.jsonl` 并从主输出剔除。
