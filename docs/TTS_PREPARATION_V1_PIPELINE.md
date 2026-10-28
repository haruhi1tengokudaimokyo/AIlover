# 三角色 TTS 准备包 V1 复现说明

本流水线只准备数据，不运行 ASR、模型训练或推理，不修改应用或文本 V3。

## 复现

在仓库根目录使用已有 Python 3.12 虚拟环境（依赖 numpy、imageio-ffmpeg）：

```powershell
.venv/Scripts/python.exe -B -X utf8 scripts/build_tts_preparation_v1.py --output finetune_data/tts_preparation_v1/新目录 --workers 8 --publish
```

先传 `--analyze-only` 可单独建立完整解码与来源核对缓存。同一 output 下再次执行会验证缓存依赖并复用结果；`--package-build` 指定新的包装子目录，不覆盖已有包装。发布只发生在四个 ZIP 均重新解压、CRC 和两次独立入口验证通过之后，拒绝覆盖已有根目录同名交付文件。

包装中断后，可检查并移出未完成的 metadata 目录，再对相同 `--package-build` 传 `--resume-packaging`；已有 ZIP 仍会重新解压并校验，不会盲目跳过。

## 输入与来源

- 从真实 XP3 索引读取声源，已有 Opus 与归档解密成员逐字节 SHA256 相同才复用。
- JA 剧本对应原始 data.xp3，ZH 对应 patch.xp3。按物理行、角色、voice ID 与出现顺序核对，不依靠语义相似度。
- 相同 voice ID 的重复出现保留所有来源行；不同中文译文保留各自来源，不自行选择其一。
- 汉化会翻译场景标签名，`scene_label_variants.jsonl` 保留双名，canonical 场景采用 JA 标签。
- `icHeart` 在原作宏中是图形，不把图形的替代文本当成实际朗读；仅有图形而无日文的记录排除，不虚构转写。
- 特典音频没有可核实的逐句转写时只记来源、时长、哈希和排除原因。
- V3 ZIP 只读，中文目标建立引用与映射。旧 V2 中文文本仍被 V3 重建工具依赖，保留。

## 声音与分区

全部原生 Opus 实际解码。已有 WAV 仅在与重新解码的 PCM 完全相同时复用；新副本为 32 kHz、单声道、16-bit PCM。保持逐句原始边界，不自动剪切、拼接或降噪。

当前技术筛选为 1–20 秒、能量、饱和比例等；它是项目策略，并非上游统一规定。高峰值与端点风险单独标记。原声完整保留，排除项逐条入账。

按整个 `.ks` 来源文件分组，优先复用 V3 的全局文件分区。参考候选从 train 来源中另外预留，不能同时出现在 train/validation/test 或少样本标签；完整 all.list 仍保留参考。少样本集合不超过十五分钟，全量合格材料同时交付。

## 使用交付包

每角色独立建立 GPT-SoVITS 实验。标签第四列是来源日文，语种固定 `ja`；汉化译文仅在跨语言索引与中文目标中。

```powershell
python -B tools/verify.py verify --root C:/解压目录/AIlover_TTS_Finetune_Preparation_V1
python -B tools/verify.py paths --root C:/解压目录/AIlover_TTS_Finetune_Preparation_V1 --character hika
```

`paths` 在包外写绝对路径 `.list`，避免修改受 SHA256 清单管理的原包。上传另一台训练机器后重新生成其本机路径。模型版本和底模必须在后续实验时固定，相关官方依据见 [研究记录](TTS_PREPARATION_RESEARCH.md)。

## 验证与限制

标准库校验器检查每个交付文件的大小和 SHA256、每个 WAV 的帧与 PCM、真实来源剧本行、日文标签、三角色身份、中文译文变体、分区隔离、重复音频、清单完整覆盖和中文监督状态。ZIP 交付后实际解压，分别调用仓库模块与随包校验工具。冻结旧资料、源归档、原生音频、文本 V3 在最后重新核对哈希。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m unittest discover -s scripts -p test_tts_audio_qc.py
.venv/Scripts/python.exe -B -X utf8 -m unittest discover -s scripts -p test_tts_preparation_verify.py
.venv/Scripts/python.exe -B -X utf8 -m unittest discover -s scripts -p test_tts_preparation_builder.py
```

自动检查不等于人工听审。所有转写是可追溯的原作剧本标签，尚未逐条听审确认朗读与字幕完全一致；背景音乐、多人重叠、实际截断的确认数量是未测。参考也只是待试听候选，不能称为已证实最优。人工任务表在 `audit/listening_review.csv`。

当前真实中文录音和有效中文语音监督配对均为零。材料可供日语角色适配准备，以及后续多语种底模的日语参考到中文目标任务；不能作为已经完成中文监督训练或中文声音效果合格的证明。

过期 ZIP 的删除前路径、大小和 SHA256 记录在根目录 `AIlover_TTS_V1_旧包清理记录.json`。本轮试制失败的包装目录属于新的临时输出，成功交付后可清理，不涉及原始输入。
