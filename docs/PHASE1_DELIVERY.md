# Phase 1 实际修改与交付清单

仓库在本轮开始前已有大量未提交修改。本清单仅记录本轮增量工作，不能把完整 `git diff` 中既有登录、记忆、语音等改动归为本轮成果。没有提交 Git、发布项目、修改 `.env`、重置数据库或执行真实迁移。

| 文件 | 本轮作用 |
| --- | --- |
| `backend/web/documents/utils/story_pipeline.py` | 新增保守解析、来源 ID / 哈希、上下文、审核、增量缓存、审计与原子 bundle |
| `scripts/build_story_data.py` | 新增显式本地构建入口，沿用既有清洗函数 |
| `scripts/parse_scenario.py` | 旧入口复用新解析器，保留 file/char/voice/text 字段并添加 provenance |
| `scripts/build_character_data.py` | 向旧清洗记录透传 source_id/location/hash，不重新生成或覆盖既有库 |
| `backend/web/documents/utils/story_retriever.py` | Lore / Style、CJK postings、Dense/RRF、过滤、门限、降级、reranker 契约与配置指纹 |
| `backend/web/documents/utils/style_retriever.py` | 只新增零命中时拒绝无关本地填充，保留旧索引兼容 |
| `backend/web/documents/utils/context_builder.py` | 独立预算、去重、历史消息对、身份模式、证据 JSON 消息 |
| `backend/web/views/friend/message/chat/chat.py` | 新构造流程、legacy/off 回退、记忆开关、请求 ID、开发 trace、消费侧时序 |
| `backend/web/management/commands/build_story_index.py` | 默认离线检查，显式 --dense 构建两种向量表 |
| `backend/web/management/commands/doctor.py` | 在既有诊断中加入模式、bundle 路径与两通道计数 |
| `backend/web/documents/utils/retrieval_evaluation.py` | 新增合成消融与指标计算 |
| `backend/web/management/commands/evaluate_retrieval.py` | 新增默认离线评测入口 |
| `backend/web/management/commands/benchmark_retrieval.py` | 新增真实本地语料 Sparse 冷/热延迟测量 |
| `backend/web/management/commands/evaluate_roleplay.py` | 增加四种 variant，修复历史拼接删除证据，保留人工评分与显式 API 开关 |
| `backend/evaluation/retrieval_synthetic.json` | 新增 10 个可审核合成用例，不含真实剧情事实 |
| `backend/web/test_story.py` | 新增 14 项解析/检索/上下文/评测集成与故障测试 |
| `backend/web/tests.py` | 调整一个依赖无关填充的旧断言，保留其余回归 |
| `frontend/.../input_field/InputField.vue` | 增加默认关闭的 DEV trace 面板，没有重写前端或播放器 |
| `.env.example` / `.gitignore` / `README.md` | 新增可关闭配置、本地语料/索引忽略规则与文档入口 |
| `docs/*.md` / `docs/evaluation/*.json` / `PROJECT_TECHNICAL_HIGHLIGHTS.md` | 架构、数据、评测、路线、修改清单、实际统计与面试材料 |

## 数据和 migrations

新增 JSONL 数据契约见 DATA_PIPELINE。没有增加 Django 数据模型或 migration。已有 `0010_friend_memory_controls.py` 在开始时已存在，不能算本轮新增。真实 SQLite、用户聊天、图片、密钥、游戏源文件均未修改。

本地构建目录 `extracted/story_builds/phase1-v1` 至 `phase1-v4` 保留；最终 v4 使用 v3 的全部源文件缓存。只有脱敏统计写入文档，没有将游戏正文/音频加入 Git。Dense 实际库存取测试使用临时合成数据与 Mock Embedding，未建立付费真实索引。

## 运行与回退

从仓库根目录使用当前终端环境（不自动改真实配置）：

```powershell
$env:STORY_DATA_DIR = 'D:\AIlover\extracted\story_builds\phase1-v4'
$env:ROLEPLAY_RAG_MODE = 'story'
.\.venv\Scripts\python.exe backend/manage.py build_story_index
.\.venv\Scripts\python.exe backend/manage.py runserver
# 或沿用原 launcher.py 桌面入口；本轮尚未重新验收 EXE。
# 回退到既有单句路径：
$env:ROLEPLAY_RAG_MODE = 'legacy'
# 完全关闭原作检索：
$env:ROLEPLAY_RAG_MODE = 'off'
```

完整构建、审核、Dense 付费开关与测试命令见 DATA_PIPELINE / EVALUATION。默认 bundle 未指定时，两通道为空并可正常进行角色卡聊天。开发面板需要后端 DEBUG 与 ROLEPLAY_DEBUG_TRACE，以及前端 dev server 的 VITE_ROLEPLAY_DEBUG；生产 bundle 不显示面板。

## 已完成、接口与未验证

已完成 Phase 1 的可运行链路：真实数据构建 → 本地检索 → 已鉴权聊天 Context → 原有模型流。offline tests 验证模型调用前的完整输入与故障行为；未调用真实 API，因此最后的角色回复质量未验证。Lite RAG 的真实延迟已测，真实 Dense/角色效果未测。

Dense provider 与 reranker 已有可替换接口及 Mock/实际库测试；身份/过滤可配置；跨语言 Sparse 仅显式映射，不支持任意中文语义。剧情数据通道完整，但真实 Lore 审核缺失。基础 trace/面板已完成，正文/源消息浏览和完整 TTS 观测尚未完成。

Phase 2 结构化记忆、持久后台任务、生命周期界面未实现；Phase 3 句子缓冲/逐轮取消协议/完整语音指标未实现；Phase 4 真实 gold、真实模型/Embedding 消融和盲评未执行。没有用空接口宣称这些能力已完成。

下一步人工事项：先核对来源审计和 KAG 跳转宏，填写带来源哈希的 Lore sidecar；建立真实检索 gold；选择/校准 Embedding，再显式构建；在私有环境开启真实模型评测并人工评分。记忆阶段开始前使用既有 backup_data 命令备份，并评审迁移与 tombstone 方案。
