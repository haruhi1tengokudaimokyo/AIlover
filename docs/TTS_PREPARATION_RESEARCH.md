# 原作日语配音的 TTS 材料准备核对

核对日期：2026-10-23。只读研究官方仓库、源码与维护者 Wiki；未下载模型、运行 ASR、训练、语音克隆或推理。以下“建议”是面向本项目的整理方案，不是已经验收的声音效果。

## 音频与转写必须保持同一种语言

GPT-SoVITS 的 `.list` 为 `音频路径|说话人|语种|实际转写`。日语原声对应 `ja` 和日文实际台词；中文译稿属于另一套文本材料，不能替换日语 WAV 的转写。[官方格式](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/README.md#dataset-format)、[实际语言解析代码](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/GPT_SoVITS/prepare_datasets/1-get-text.py#L105-L132)。

跨语言是“参考音频/参考文字为 A，目标合成文字为 B”，或“训练语言 A、目标语言 B”。维护者 2024-10-23 的说明提醒：少量微调可能保留底模跨语言能力，大量单语微调可能削弱它。日语完整语料应保留，同时另外提供精选小集合；不能承诺小时级日语全量训练后中文一定更好。[官方跨语言说明](https://github.com/RVC-Boss/GPT-SoVITS/wiki/不同训练集的跨语种能力(Cross‐Language-Ability-of-Different-Training-Sets))。

## 面向游戏原声的可复现整理建议

1. 保留原始归档与抽取文件，用游戏脚本的说话人、voice ID 建立关联，记录归档条目、哈希、剧本路径/行号。项目已经有可用 XP3/KAG 工具，优先复用。GARbro 官方列出 KiriKiri XP3 支持，可作为格式研究参照，不代表它支持每个新游戏。[格式清单](https://github.com/morkt/GARbro/blob/master/docs/supported.html)、[XP3 实现](https://github.com/morkt/GARbro/blob/master/ArcFormats/KiriKiri/ArcXP3.cs)。
2. 原文与声音按 voice ID 对齐；同一声音被多条剧本文本复用时，检查实际完整转写，不把一份完整音频重复标成几个不完整句子。无语音台词、缺失文件、重复音频、字幕与配音差异单独列出，不能靠翻译补造音频监督。
3. 留三层材料：原始全量档案、可对齐的完整日语材料、适合首次微调的精选包。全量档案不等于每个音频都应参与训练；纯发声、多人重叠、坏文件和文本不匹配要显式标记。
4. 已经逐句切好的游戏文件不必盲目再次切碎；仅对长片段或明显长静音切分，切后重新校对对应文本。自动切片使用静音/RMS，并不理解句意。[官方切片工具](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/tools/slice_audio.py)、[audio-slicer 原项目](https://github.com/openvpi/audio-slicer#parameters)。
5. 游戏脚本能精确对齐时先利用原文；ASR 只用于缺稿或核验，再人工校正。GPT-SoVITS 的 Faster Whisper 包装调用 `transcribe` 并接收语种参数，可明确选日语，不应使用翻译任务替代原语种转写。[官方 ASR 实现](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/tools/asr/fasterwhisper_asr.py#L97-L127)。

## 格式、命名与参考音频

官方特征预处理把声音重采样到 32 kHz 并写出 int16。本项目使用 32 kHz、单声道、16-bit PCM 作为可复现交换格式合理，同时保留原始 Opus；转高采样率不会找回原始压缩丢失的细节。[官方预处理](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py#L79-L123)。

当前文本预处理按文件 basename 标识特征，须避免同名文件冲突。维护者 FAQ 还说明 `.list` 说话人列并不作为多说话人隔离机制：麦、绯华、菖蒲应分别准备清单和实验目录。[命名实现](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/GPT_SoVITS/prepare_datasets/1-get-text.py#L84-L99)、[维护者 FAQ](https://github.com/RVC-Boss/GPT-SoVITS/wiki/用户指南(教程)&常见问题解答-User-Guide-&-FAQ-(Frequently-Asked-Question))。

当前 `inference_webui.py` 对有参考音频模式检查 3–10 秒。可为每角色精选数段 5–10 秒的完整、干净日常台词及准确日文文本，另留参考文件的来源清单；参考语言为日语，未来合成中文时目标语言另设中文。项目训练集的 2–15 秒阈值属于本地质量筛选，不是上述参考长度检查，也不是官方对所有训练文件的统一限制。[参考长度及两个语言参数](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/GPT_SoVITS/inference_webui.py#L827-L938)。

## 版本边界

核对时 GitHub Releases 标记 Latest 的发布是 `20250606v2pro`；main 与 Wiki 已继续变化，不能把发布标签、整合包版本和模型版本混为一个版本号。[发布页](https://github.com/RVC-Boss/GPT-SoVITS/releases/tag/20250606v2pro)。

维护者版本 Wiki 于 2026-10-07 更新：压缩/噪声较明显的数据与高质量录音适配的路线不同；v4 支持微调，v5 的少样本微调当时尚未研究和试验。后续训练应先固定仓库 commit、底模、模型路线和工具版本，再选择方案；本次不启动训练，也不据版本宣传推断本游戏的效果。[官方版本比较](https://github.com/RVC-Boss/GPT-SoVITS/wiki/GPT‐SoVITS‐features(Latest‐Including‐v5))。

首次尝试建议保留全量档案，并提供一个独立的少样本候选包以及若干参考音频供之后对照；具体时长是实验选择，不能把官方提到的 1–30 分钟范围当作效果保证。实际质量仍需之后用固定测试文本、日语/中文分别试听与评估。本记录只完成材料方法核对。
