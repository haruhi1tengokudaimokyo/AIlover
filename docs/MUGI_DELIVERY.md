# 麦（むぎ）角色与微调材料交付

更新：2026-10-22。对应本地游戏《王様恋愛》的第一位女仆，slug 为 `mugi`。
本次完成材料提取、角色创建和现有前端/后端接入；没有训练模型或调用外部翻译、声音克隆服务。

## 与前两位样例对齐的完成项

| 项目 | 麦的实际产物 |
|---|---|
| 身份和素材编号 | むぎ，游戏角色 1，语音前缀 `vo1_` |
| 原始台词 | 66 个脚本、1719 条可确证归属记录，附来源 ID、行号和 SHA256 |
| 原始声音 | 从本地 `voice.xp3` 提取 1776 个 Opus，附逐文件哈希 |
| 干净日常台词 | 1140 条，全部有对应声音；称呼/自称/语尾统计、120 条抽样、60 条参考候选 |
| TTS 转码 | 1140 个 WAV，32 kHz / 单声道 / 16-bit PCM |
| GPT-SoVITS 标注 | 1038 条、4584.739 秒（1.274 小时）；102 条时长不在 2–15 秒内，不参与训练 |
| 日常参考声音 | 3 组 WAV/TXT，5.143、5.132、6.394 秒；另有原始 Opus/TXT 克隆参考 |
| LLM 原文材料 | 1140 条日文来源，训练输入仅保留同分段前文 |
| 中文材料 | 5 组明确标为中文改写的角色卡示例、独立词典、翻译/续跑/质检/ShareGPT 入口 |
| 角色卡 | 身份、性格、称呼、说话方式、开场白、3 个快捷话题、`MUGI_VOICE` |
| 游戏美术 | 559×1600 透明立绘、384×384 头像、1600×900 房间背景 |
| 前端 | 首页三位游戏角色使用相同立绘精选卡；复用搜索、好友、普通/沉浸聊天工作区和静态角色舞台 |
| 后端 | 已创建本机角色与好友；旧风格检索和 Story-Aware RAG 均已安装麦的语料 |

## 本地文件位置

- `extracted/characters/mugi/`：原始记录、清洗语料、统计、候选、抽样与来源哈希。
- `extracted/voice/vo1_*.opus`：原始声音。
- `finetune_data/mugi/tts/`：训练音频、`mugi.list`、三组参考和质检报告。
- `finetune_data/mugi/llm/source/`：日文来源与安全前文；`llm/output/` 为中文种子及后续真实翻译输出。
- `backend/seed_cards/mugi.json`：实际角色卡。
- `backend/seed_assets/mugi/voice_ref.opus` / `.txt`：第一条日常参考的原始音频与台词。
- `backend/media/character/stage/mugi-{portrait,avatar,background}.webp`：前端实际使用的美术。
- `backend/web/documents/character_lines/mugi.jsonl`：旧风格检索语料。
- `backend/story_data/`：已启用的三角色检索包，等同于本地 `extracted/story_builds/three-characters-20261022-v3`。

原文、声音、生成的训练集和游戏图片均被 Git 忽略。Git 中只保留源码、角色卡改写、说明、词典与无原文的统计报告。

## 身份、人物卡与选图依据

`Init_VariableADV.ks` 的角色数组确认编号 1 为むぎ，2 为緋華，8 为菖蒲。
开场 `main/0_1.ks` 使用 `bg5_0` 和 `ch=1 dr4 f=111`；
`Init_VariableSTAND.ks` 的 `STI_Base[1][1][4]=[8,0,0,0,0]` 决定使用 body8、表情1、无配件。
最终图层为 `2/stb1_s2_1_8.tlg` 与 `2/st1_s2_1_1.tlg`，按原画布坐标合成，没有套用其他角色的身体，也没有自创人物。

人物卡的口头敲门、自称麦酱、要求反应、自夸可爱和寿司话题来自 `0_1.ks` 的日常段落；
打扫比试与女仆自尊来自 `0_3.ks`，女仆一号自我介绍来自 `0_10.ks`。
陪伴语气和五组中文示例是依据这些特征编写的产品改写，不是原文翻译或已审核剧情事实。
没有补造姓氏、年龄、身世或恋爱路线。

## 清洗、隔离与数据保护

原始记录完整保留。训练材料在旧行级过滤基础上，仅为麦增加明确 `H_Start` 场景、精准露骨词组、纯喘息、吻声与睡声过滤。
上下文以完整来源记录复核，保证同文件、同分段且早于目标；不能将目标回复或未来台词泄漏进训练输入。
这是保守规则与定向文本审校，不能等同于逐条人工试听或完整内容审查。

原两位的原始/清洗/训练文件 3188 项逐文件 SHA256 核对没有变化。
数据库升级前保留了 `backend/backups/before-mugi-20261022-181239/db.sqlite3`；
旧角色、好友、消息、记忆和系统提示逐行核对未变，只添加了麦的角色与好友。
`seed_ousama --slug mugi` 只更新麦；即使另一位角色改名为“麦”，也不会被覆盖。麦改名后重复运行不会再创建一位。

Story 解析缓存升级版本，避免直接复用旧缓存中 `character=null` 的麦记录。
已启用索引包含绯华 1960、菖蒲 1312、麦 1140 条风格示例；旧两位示例逐条比对不变。
原索引目录完整保留为 `backend/story_data-backup-*`，没有编造 Lore，已审核剧情事实仍为 0。

## 验证结果与范围

- 后端 81 项测试通过，包含角色隔离、素材接口、缓存重解析、检索、SSE/语音回归及交付保护。
- 前端 20 项测试、类型检查和 Vite 生产构建通过，Django 模板哈希已同步；继续使用原有公共工作区，不新增角色专用聊天组件。
- 游戏叠层 4 项测试、训练保护 7 项测试通过。
- `scripts/verify_mugi_training.py` 已实际检查全部 WAV 格式、训练标注、重复路径、参考对应及旧文件哈希。
  3 个训练片段峰值达到 0.98 满幅，报告保留标记；三条参考均低于该值。没有声称已人工逐条试听。
- 实际运行隔离 SQLite 副本的 Django 服务：麦的首页搜索、创建/加载好友、聊天路由和三张图片 HTTP 请求全部成功。
  没有向真实用户数据库写测试聊天。
- 实际上下文预览注入麦的 4 条风格证据，预算内；本地检索对日常问题命中、无关问题返回 0，没有调用 API。

报告：`docs/evaluation/mugi-http-smoke.json`、`context-preview-mugi.json`、`retrieval-mugi.json`；
训练详细统计见 `finetune_data/mugi/{source_summary.json,verification.json,llm/build_summary.json}`。

本次 Computer Use 因无法可靠识别浏览器 URL 而自动停止，未完成新的浏览器点击、手机视口或沉浸切换实测。
现有工作区实现与先前验收记录保留；本次前端确认范围为实际接口、资源和既有组件的测试/类型检查。

## 使用与重建

本机已完成角色与材料安装。启动项目后，在首页搜索“麦”，或在好友列表选择麦进入聊天。
声音目前仍遵循原默认配置；若已有合法可用的克隆音色，将 ID 填入 `MUGI_VOICE` 后运行角色命令。

```powershell
cd D:\AIlover
.venv/Scripts/python.exe scripts/prepare_mugi_training.py --reuse-audio
.venv/Scripts/python.exe scripts/verify_mugi_training.py
.venv/Scripts/python.exe scripts/prepare_game_stage.py --character mugi
.venv/Scripts/python.exe backend/manage.py seed_ousama --slug mugi
.venv/Scripts/python.exe backend/manage.py runserver 127.0.0.1:8000
```

首次从游戏提取时省略 `--reuse-audio`；已有音频复用前会逐个核对哈希。
如重建了清洗材料，需要同步 `lines_clean.jsonl` 到运行时 `character_lines/mugi.jsonl`，
再用 `scripts/build_story_data.py --output <新的目录>` 构建三角色 bundle，并通过 `STORY_DATA_DIR` 切到新目录。
不要覆盖已有 bundle。原始索引缓存可用 `--previous` 复用，过滤规则仍会重新应用。

**全量中文翻译、模型训练、原声克隆及真实 LLM/TTS/ASR 效果尚未执行或验收。**
当前真正可用的中文 seed 是 5 条，`sharegpt.json` 是空数组，不注册为空的完整语料，也没有将日文 mock 冒充中文。
后续真实翻译入口、续跑方法和训练路径见 [麦的微调准备说明](../finetune_data/mugi/README.md)。
