# GPT-SoVITS 微调数据集（hika、ayame）

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
