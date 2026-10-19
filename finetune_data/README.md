# 微调前期准备总手册（TTS + LLM）

> 生成日期：2026-10-19。本目录是「云端训练 + 本地推理」的全部前期准备产物。
> 本地硬件：笔记本无 GPU / 实验室 GTX 1660 6GB —— 训练在云端（AutoDL），推理回本地。

## 目录结构

```
finetune_data/
├── README.md                  ← 本文件（总手册）
├── tts/                       ← TTS（GPT-SoVITS）数据集，已就绪，可直接上传训练
│   ├── build_dataset.py       ← 数据集构建脚本（可重跑）
│   ├── dataset/hika/          ← 绯华 wav 1871 个（32kHz 单声道 16bit）
│   ├── dataset/ayame/         ← 菖蒲 wav 1284 个
│   ├── hika.list              ← GPT-SoVITS 标注 1784 条（DATASET_ROOT 占位符）
│   ├── ayame.list             ← GPT-SoVITS 标注 1219 条
│   ├── reference/             ← 每角色 3 条参考音频 + 台词（零样本验证用）
│   ├── qa_report.md           ← 质检报告（合计 4.41 小时可用数据）
│   └── README.md              ← TTS 上传/训练细节
└── llm/                       ← LLM（Qwen LoRA）数据管线，待填 API key 后跑翻译
    ├── translate_corpus.py    ← 日→中翻译管线（断点续跑/质检/重试）
    ├── glossary.json          ← 36 条角色译名/口癖对照
    ├── build_sharegpt.py      ← 翻译结果 → LLaMA-Factory sharegpt 格式
    ├── output/seed_samples.json ← 10 条种子样本（角色卡示例，已可用）
    └── README.md              ← LLM 数据生成细节
```

## 现状：各模块就绪度

| 模块 | 状态 | 下一步 |
|---|---|---|
| TTS 数据集 | ✅ **完成**，3003 条 / 4.41 小时，远超 GPT-SoVITS 门槛 | 上传 AutoDL 即可开训 |
| TTS 零样本参考音频 | ✅ 每角色 3 条已选好 | 也可先拿去百炼声音复刻免费试音色 |
| LLM 翻译管线 | ✅ 脚本就绪（mock 验证通过） | 项目根建 `.env` 填百炼 API_KEY 后跑全量 |
| LLM 种子样本 | ✅ 10 条中文示例已转 sharegpt | — |
| LLM 全量语料 | ⏳ 待翻译（3272 条，预估 ¥10–20，30–60 分钟） | 按 `llm/README.md` 七步操作 |

## 云端训练操作流程（AutoDL）

### TTS：GPT-SoVITS 微调（预估 ¥4–8/角色，2–4 小时）

1. AutoDL 租 4090（¥1.88/时），镜像选 CodeWithGPU 社区 **GPT-SoVITS-Official**
2. 先用「无卡模式」（¥0.1/时）开机上传 `tts/` 整个目录到 `/root/GPT-SoVITS/data/tts/`
3. 修正标注路径：
   ```bash
   sed -i 's|DATASET_ROOT|/root/GPT-SoVITS/data/tts/dataset|g' hika.list ayame.list
   ```
4. 正常开机 → WebUI → 训练集填 `hika.list`（标注语种 ja）→ 一键微调；ayame 同理
5. **推理时目标语种选 zh（中文）**——日文训练的音色直接合成中文语音
6. 下载 `GPT_weights/` 和 `SoVITS_weights/` 回本地

### LLM：Qwen2.5-7B LoRA（预估 ¥4–12，2–6 小时）

1. 本地先跑完翻译管线（见 `llm/README.md`），产出 `sharegpt.json`
2. AutoDL 租 4090，镜像选 LLaMA-Factory 社区镜像
3. 上传 `sharegpt.json` 到 `LLaMA-Factory/data/`，把 `output/dataset_info.json` 片段合并进 `data/dataset_info.json`
4. WebUI：基座 Qwen2.5-7B-Instruct、LoRA（rank 16 / alpha 32）、sharegpt 格式、qwen 模板、cutoff 2048、lr 1e-4、2–3 epochs
5. 导出合并模型，下载回本地

### 本地推理部署（GTX 1660 6GB）

- **TTS**：GPT-SoVITS 推理门槛 4GB 显存，1660 可用（10 秒语音约 3 秒生成）；
  写一个本地 provider 接入 `backend/web/views/friend/message/chat/voice.py` 的 stream 接口（与 CloudTTSProvider 平行），GPT-SoVITS 起 `api_v2.py` HTTP 服务
- **LLM**：1660 跑 7B Q4 约 10–20 tokens/s，可用但不算流畅；**建议文字继续走百炼 API，语音走本地**——语音是情感核心且推理便宜

## 费用总览

| 项目 | 费用 |
|---|---|
| TTS 微调（2 角色） | ¥8–16 |
| LLM 翻译（deepseek-v3.2，3272 条） | ¥10–20 |
| LLM LoRA 训练 | ¥4–12 |
| **合计** | **约 ¥22–48** |

## 注意事项

- galgame 语音/剧本版权属 ASa Project，微调产物仅限个人非商用学习
- 训练前建议先用 `tts/reference/` 的音频在百炼声音复刻（免费）做零样本基线对比
- 翻译完成后务必检查 `llm/qc_failed.jsonl`，删掉对应记录重跑会自动补翻
- mock 产物（`llm/output/translated.jsonl`、`sharegpt.json`）在跑真实翻译前先删除
