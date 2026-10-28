# 麦与水无月萤：语音准备的实际边界

准备方式参考 GPT-SoVITS 官方仓库，固定提交 `b4570b876f5c086819ba84e3215472733c6a7b70`。配置字段来自该版本的 `webui.py`，不是凭空拼接的参数。

云端目录：`/root/autodl-tmp/ailover/speech/{mugi,hotaru}`。每个角色有绝对路径清单、逐文件 SHA256/时长审计、S1/S2 配置和特征提取环境配置。包内原数据不修改、不重复保存音频。

已实际验证：

| 角色 | train | validation | test | 初次适配子集 |
| --- | ---: | ---: | ---: | ---: |
| 麦 | 1196条 / 1.574小时 | 228条 / 0.298小时 | 260条 / 0.406小时 | 183条 / 约15分钟 |
| 萤 | 2704条 / 3.989小时 | 355条 / 0.474小时 | 497条 / 0.727小时 | 164条 / 约15分钟 |

此外，每人3条参考音频保留在原包中，不加入训练。三个分区没有音频 SHA256 交集；少样本子集严格来自 train。原包已另行验证按来源场景划分。完整训练清单全部保留，初次15分钟试验不是删除其余数据。

音频均为32kHz、单声道、16-bit PCM，标签全部是日语。现有材料没有真实中文配音监督对。日语适配后的中文发音、音色还原和情绪都需要后续真实合成与听评，文件校验不能证明这些效果。

## 已启动的准备任务

`bootstrap_speech.sh` 在独立 venv 安装官方依赖，约束 Torch/torchaudio 2.5.1，复用已验证的 CUDA，不改动文本环境。`download_speech_assets.py` 从官方安装脚本使用的 ModelScope 地址下载模型和字典，校验压缩包并记录 SHA256，仅解压本次 v2Pro 所需模型。

日志：`/root/autodl-tmp/ailover/logs/speech-preparation.log`。

真实状态依次查看：

- `reports/speech-data-ready.json`：清单和配置已验证。
- `reports/speech-environment-ready.json`：依赖可导入、CUDA及ffmpeg可用。
- `reports/speech-assets-ready.json`：预训练资产下载、校验及必要文件检查通过。

缺少后两份文件时，不得声称语音环境全部准备完成。

本轮只准备语音环境、材料和配置；没有启动语音训练或推理。后续GPU步骤应串行：文本任务结束 → 官方四步特征提取（文本、HuBERT、说话人向量、semantic）→ 核对产物完整性 → S2/S1适配。特征脚本会逐条捕获异常，所以不能仅凭进程退出码判定全部成功。

初始配置为 v2Pro、batch4、S1/S2各8轮、每轮留权重；这是待短测的起点，不是已经验证的最优参数。不要仅看训练loss选最终声音，需要独立中文文本、数字/多音字/长句、音色与自然度听评。禁止将日语音频配中文转写训练，禁止把生成语音冒充原始录音。

官方参考：

- https://github.com/RVC-Boss/GPT-SoVITS
- https://github.com/RVC-Boss/GPT-SoVITS/blob/b4570b876f5c086819ba84e3215472733c6a7b70/webui.py
- https://github.com/RVC-Boss/GPT-SoVITS/blob/b4570b876f5c086819ba84e3215472733c6a7b70/install.sh
