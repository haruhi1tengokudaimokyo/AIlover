# 文本 V3 构建与审查

本流程仅处理三位角色的中文文本。没有训练、调用外部模型、重构应用或修改语音包。

## 文件与复现

- `scripts/build_text_corpus_v3.py`：查找并校验实际 V2 文本包，从本地汉化补丁重新提取到独立 V3 目录，构建、质检、打包和解压验证。
- `scripts/text_corpus_v3_common.py`：纯标准库规则与校验器，副本随每个 ZIP 发布；会重读包内原始 KS，而非只相信派生 JSON。
- `scripts/text_v3_editorial.py`：小规模离线合成候选和另行设计的开放留出题；没有伪装成游戏原文或真人标注。
- `scripts/test_text_corpus_v3.py`：上下文、身份、角色、分区、近重复、候选审核、路径和审查表回归。
- `scripts/check_text_v3_failure_modes.py`：在一次性包副本上主动篡改，再更新外层清单，确认来源/语义规则仍能拒绝坏数据。
- `scripts/compare_text_v3_builds.py`：比较两个独立构建的三个 ZIP 的 SHA256，并再次复核受保护输入和审查表覆盖。

在仓库根目录运行（Python 3.10+，无额外依赖）：

```powershell
python -B -X utf8 scripts/build_text_corpus_v3.py --output finetune_data/text_v3/新的独立目录 --self-test
```

默认从仓库首层查找 V2 ZIP 并读取其元信息；不同位置用 `--v2-dir`。原始日文 KS 目录用 `--jp-dir`，
游戏文件夹用 `--game-dir`。构建目录必须是仓库内的全新目录，不覆盖 V2、既有 V3 或原游戏。
`--publish` 只将完成验证的交付复制到仓库首层；如果同名 V3 交付已存在则拒绝覆盖。
ZIP 固定成员顺序和元数据时间戳，数据划分使用固定种子；同一输入和脚本版本可复现相同包哈希。

本次正式构建目录为 `finetune_data/text_v3/final-20261022`，独立重建目录为 `finetune_data/text_v3/reproducibility-20261022`。
三个 ZIP 的重建哈希均一致；再次核对的 116 个受保护输入未变。记录在首层 Checks.json 的 reproducibility 字段。
实际执行通过 18 项回归和 8 类重算清单后的故障注入；人工审查表每角 55 条，总计 165 条。

## 人工审核

首层 Review.csv 每角至少五十条，包含合格原作、隔离样本和未批准的合成候选。未替用户填 decision 或署名。
目前合成均未获得人工批准，默认 mixed 与 canonical 相同；不能把候选数量当成已进入训练的数量。

如需批准合成候选，建立 JSONL，每行含 `sample_id`、`payload_sha256`、`decision`、`reviewer`。
decision 为 approve，reviewer 必须是实际审查人的署名；不可由构建器假署名。重新构建时用 `--reviews 文件路径`。
内容哈希不符或未知 ID 会失败。相同场景模板固定在一个分区；批准后也不会把合成验证/测试候选放进训练。
训练分区合成样本最多占四分之一，不自动复制或过采样候选凑比例。
原作隔离样本不能通过批准合成候选的文件强行回流，需人工明确来源/语义，修复规则或以独立来源校订流程重新构建。

## 格式与比较

每个包的 `sft/dataset_info.json` 登记 canonical_context_only 与 mixed_sft_v3 的独立 train / validation / test。
README 说明 Qwen/LLaMA-Factory 的 ShareGPT 字段和身份模式；模型、template、token 截断和显存配置由实际训练环境确定。
`baseline_reference/` 保留 V2 包内字节与原清单，未修改旧数据，且不默认注册进 V3 训练。
V2 的旧训练样本可能与 V3 新测试场景重叠，比较两者时需使用共同未见题，不能把新的文件划分当成 V2 从未接触。

最终测试题不得作为生成提示词、训练内容或调参集。`tools/verify.py score` 只检查真实模型回答的空答、假名和缺测；
角色还原、语义正确、中文自然度由人工盲评。没有回答时不会伪造模型得分。

研究方法与本地实际统计、限制、SHA256 均记录在首层 Report.md 与 Checks.json。阅读过的方法来源：

- [ChatHaruhi](https://github.com/LC1332/Chat-Haruhi-Suzumiya)
- [RoleLLM](https://github.com/InteractiveNLP-Team/RoleLLM-public)
- [Character-LLM](https://aclanthology.org/2023.emnlp-main.814/)
- [CoSER](https://github.com/Neph0s/CoSER)
- [LLaMA-Factory 数据准备](https://llamafactory.readthedocs.io/en/latest/getting_started/data_preparation.html)
