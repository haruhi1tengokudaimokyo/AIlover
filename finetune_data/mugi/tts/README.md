# 麦 GPT-SoVITS 数据集

此目录由原有 `finetune_data/tts/build_dataset.py` 生成，单独输出，未覆盖绯华或菖蒲。
`dataset/mugi/` 为 32 kHz、单声道、16-bit PCM；`mugi.list` 第三列为 `ja`。
时长限定 2–15 秒；`reference/mugi_ref_1..3.wav` 为 5–10 秒参考，配套 `.txt` 是日文原文。
详细数量、排除原因、时长和参考来源见 `qa_report.md`。

上传本目录后，将标注里的字面 `DATASET_ROOT` 替换为云端 `dataset` 的绝对路径。
例如：`sed -i 's|DATASET_ROOT|/root/GPT-SoVITS/data/mugi/tts/dataset|g' mugi.list`。
选择麦自己的标注单独训练；参考文本语种设 `ja`。尚未训练或验证中文跨语种音色。

重建：在项目根执行 `.venv/Scripts/python.exe scripts/prepare_mugi_training.py --skip-source`。
原始声音和训练音频仅留在本机。`seed_assets/mugi/voice_ref.opus` 保留原始 Opus 参考，
并与 `reference/mugi_ref_1.txt` 对应；未调用任何声音克隆服务。
