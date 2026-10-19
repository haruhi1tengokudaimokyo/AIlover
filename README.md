# AIlover — 二次元角色 AI 聊天桌面应用

2026-10-14源码升级已实现Phase1–4工程链路：带来源KAG上下文、双通道Hybrid RAG、结构化记忆、可中断语音、离线消融及私有开发证据面板。默认本地风格bundle已构建；真实Lore及人物还原质量尚待人工审核和真实模型评测。见 [最终交付与命令](docs/PHASE4_DELIVERY.md)、[评测](docs/EVALUATION.md)、[技术亮点](PROJECT_TECHNICAL_HIGHLIGHTS.md)。旧EXE需要重建验收；以下旧素材/音色说明不属于本轮实施，本轮不进行模型训练。

Django + LangGraph 后端 + Vue 3 前端，支持流式对话、语音合成（TTS）、语音识别（ASR）、长期记忆。
可打包为 Windows 桌面 exe，内置「丛雨」（《千恋＊万花》）角色卡。

### 本次修复后的开发入口

在仓库根目录复制 `.env.example` 为 `.env`，填入 `API_KEY` 和 `API_BASE`。
先设 `TTS_ENABLED=false` 测试文字对话，再接通语音。不要把密钥提交到 Git。

```powershell
.venv/Scripts/python.exe backend/manage.py check
.venv/Scripts/python.exe backend/manage.py migrate
.venv/Scripts/python.exe backend/manage.py doctor
.venv/Scripts/python.exe launcher.py
```

已存在账号和角色时不必重建。无角色时先注册，再运行
`.venv/Scripts/python.exe backend/manage.py seed_ousama --username 你的用户名`。

聊天窗口支持「纯文字 / 语音开启」、停止回复以及错误提示。语音故障时继续返回文字；
生成失败或用户中断的回复不会写入历史。默认结构化记忆由成功消息的持久MemoryJob提取，支持纠错/遗忘/来源；旧摘要模式保留为兼容路径。
默认本地Sparse双通道检索，无关问题允许空结果。Dense需显式 `build_story_index --dense` 并启用，旧 `build_style_index` 保留。可用 `EMBEDDING_*` 和 `TTS_API_KEY` 单独配置服务。

前端 `npm run dev` / `npm run build` 自动从依赖准备 VAD 资源。
重新构建前端后仍需运行 `scripts/sync_template.py`。源码更新不会自动更新旧的 exe。

完整检查结论见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

### 已增加的管理功能

- 侧栏「运行设置」：查看配置状态和本地/联网数据说明，不显示密钥。
- 聊天窗口「记忆与记录」：查看、纠正、关闭自动记忆、搜索、导出和清空。
- 角色编辑页：修改完整角色设定、音色ID、开场白和快捷话题。
- 同一角色会话同时只能生成一条回复；清空历史会一起清空记忆并关闭自动记忆。
- 备份：`.venv/Scripts/python.exe backend/manage.py backup_data`，包含数据库和媒体，不含 `.env`。
- 语料审计：`audit_corpus`；评估用例：`evaluate_roleplay`，默认离线。

新版桌面包在 `dist/updated/AIlover/AIlover.exe`，旧版仍保留。
新版也支持 `AIlover.exe --doctor` 和 `AIlover.exe --backup`。
需要你完成的操作见 [USER_NEXT_STEPS.md](USER_NEXT_STEPS.md)。

---

## 一、直接运行 exe（推荐）

1. 双击 `dist/AIlover/AIlover.exe`，会弹出桌面窗口（打不开时会自动改用浏览器）。
2. 首次使用先在界面里**注册一个账号**。
3. 关闭程序，在 `dist/AIlover/` 目录打开命令行，创建丛雨角色：

   ```
   AIlover.exe --seed-murasame 你的用户名
   ```

4. 重新双击 `AIlover.exe`，登录后「添加好友」选择**丛雨**即可开始聊天。

### 配置密钥（必须，否则无法对话）

在 `dist/AIlover/data/` 目录下新建 `.env` 文件（格式参考仓库根目录的 `.env.example`）：

```
API_KEY=你的阿里云百炼API-KEY
API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
WSS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/inference
```

数据（账号、聊天记录、角色图片）都保存在 exe 旁边的 `data/` 目录。

---

## 二、让丛雨用自己的声音说话

默认音色是通用女声 `longanyang`。要还原丛雨的声音，推荐两种方式：

**方式 A：阿里云百炼「声音复刻」（最简单，现有代码直接支持）**
1. 准备一段 10 秒左右的丛雨语音样本（从游戏语音或语音包截取，仅限个人学习使用）。
2. 到百炼控制台 → 声音复刻，上传样本，得到一个音色 ID。
3. 把它填进 `data/.env`：`MURASAME_VOICE=你的音色ID`，然后重新执行
   `AIlover.exe --seed-murasame 你的用户名`。
   也可以在应用的角色编辑里直接改 voice 字段。

**方式 B：本地 GPT-SoVITS（效果最好，需要 GPU）**
社区已有训练好的丛雨 GPT-SoVITS 模型（B 站搜「千恋万花 语音 GPT-SoVITS」）。
跑起 GPT-SoVITS 的 `api_v2.py` 后，把 `chat.py` 中 TTS 请求替换为对它的 HTTP 调用即可。
参考项目：https://github.com/RVC-Boss/GPT-SoVITS

> 版权提示：角色语音与形象属于柚子社（YUZUSOFT），以上方式仅供个人非商用二创学习。

---

## 三、开发模式

```bash
# 后端（仓库根目录）
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt
cd backend && ../.venv/Scripts/python manage.py migrate
../.venv/Scripts/python manage.py seed_murasame   # 注册账号后执行
../.venv/Scripts/python manage.py runserver

# 前端（另开一个终端，已配置 /api、/media 代理到 8000）
cd frontend && npm install && npm run dev
```

## 四、重新打包 exe

```bash
cd frontend && npm run build                # 构建前端到 backend/static/frontend
cd .. && .venv/Scripts/python scripts/sync_template.py   # 同步首页模板
.venv/Scripts/python -m PyInstaller ailover.spec --noconfirm
# 产物：dist/AIlover/AIlover.exe
```

调试可用 `AIlover.exe --no-window`（只起服务不开窗口，Ctrl+C 退出）。

---

## 五、《王様恋愛》角色：绯华 与 菖蒲

从游戏 `国王恋爱/`（ASa Project《王様恋愛》，Kirikiri/XP3 引擎）提取资源，
将台词最多的两位女主角——佐藤绯华（vo2，2410 条语音）和藤丘菖蒲（vo8，1792 条语音）——
做成了聊天角色。**不涉及任何模型微调**，角色还原靠三层：角色卡提示词 + 原作台词 RAG + 声音复刻。

### 资源提取（已完成）

```bash
.venv/Scripts/python scripts/xp3.py list "国王恋爱/voice.xp3"        # 列出 XP3 内容
.venv/Scripts/python scripts/xp3.py extract "国王恋爱/voice.xp3" extracted/voice vo2_   # 绯华语音
.venv/Scripts/python scripts/parse_scenario.py                       # 解析剧本 -> extracted/corpus.jsonl
.venv/Scripts/python scripts/build_character_data.py                 # 清洗语料（已剔除 R18）-> extracted/characters/
```

产物：
- `extracted/voice/vo2_*.opus`、`vo8_*.opus`：两位女主全部语音（仅个人学习使用）
- `extracted/characters/<slug>/lines_clean.jsonl`：干净台词库（绯华 1910 条 / 菖蒲 1303 条）
- `extracted/characters/<slug>/ref_candidates.txt`：声音复刻候选片段

### 接入应用（三步）

```bash
cd backend
../.venv/Scripts/python manage.py migrate
../.venv/Scripts/python manage.py seed_ousama          # 注册账号后执行，创建绯华和菖蒲
../.venv/Scripts/python manage.py build_style_index    # 需要 API_KEY：构建台词向量索引（风格 RAG）
```

- 角色卡：`backend/seed_cards/<slug>.json`（性格、口癖、示例对话、开场白、快捷话题，可手改后重跑 seed 生效）
- 台词库：`backend/web/documents/character_lines/<slug>.jsonl`
- 聊天时按用户消息检索 5 条最相关的原作台词注入提示词（日语原文，校准语气口癖，回复仍为中文）

### 角色原声

`backend/seed_assets/<slug>/voice_ref.opus`（+ 对应台词文本 `voice_ref.txt`）已备好：

- **方式 A（百炼声音复刻）**：上传 voice_ref 音频，得到音色 ID 填入 `.env` 的
  `HIKA_VOICE` / `AYAME_VOICE`，重跑 `seed_ousama`。
- **方式 B（本地 GPT-SoVITS，效果最好）**：把 `voice_ref.opus` 作为参考音频、
  `voice_ref.txt` 作为参考文本接入 GPT-SoVITS `api_v2.py`，替换 chat.py 中的 TTS 调用。

> 版权提示：游戏剧本、语音与角色形象属于 ASa Project，以上全部内容仅供个人非商用学习。

### 图片资源（尚未处理）

`bgimage.xp3`（背景 313MB）、`stimage.xp3`（立绘 752MB）、`evimage.xp3`（事件 CG 1.4GB）
尚未提取。提取后把角色立绘/背景放到 `backend/seed_assets/<slug>/photo.jpg` 和
`background.jpg`，重跑 `seed_ousama` 即可替换占位图（注意自行过滤 R18 CG）。

## Story-Aware RAG 技术升级（Phase 1）

已实现带来源与真实上下文的数据构建、剧情/风格双通道Hybrid RAG、预算和离线评测，尚无人工审核真实Lore。后续记忆、语音取消和综合评测已实现。见 [当前交付](docs/PHASE4_DELIVERY.md)、[架构](docs/ARCHITECTURE.md)、[数据流水线](docs/DATA_PIPELINE.md)。

## 结构化长期记忆（Phase 2）

已新增来源条目、纠错/遗忘、持久任务恢复和管理界面，默认 `MEMORY_MODE=structured`；需要先备份并迁移到 `0011_structured_memory`。本机已完成迁移与原有记录保留核验。具体能力边界、命令与回退见 [记忆说明](docs/MEMORY.md)。

## 流式语音与取消（Phase 3）

已实现句子缓冲、逐轮标识、私有取消接口、有序音频与播放器清理，并将主模型聊天节点改为可取消的异步调用，保留同步评测。85 项后端测试和 5 项播放器测试通过；详见 [语音说明](docs/VOICE.md)。云端音频、真实麦克风与全双工效果尚未验证，不需要训练模型或部署新服务。

## 综合评测和开发诊断（Phase 4）

新增 `evaluate_system`、隔离库真实记忆消融、严格Dense单路评测和 `score_roleplay` 人工评分入口；原有12用例加8扩展覆盖身份、纠错、遗忘与证据边界。80组合零失败、15/15记忆检查通过，均为Offline契约；开发面板按用户/好友/轮次鉴权。真实本地HTTP/SSE取消及证据验证通过，浏览器按钮/云模型/设备/新EXE尚未验收。完整结果见 [评测](docs/EVALUATION.md)。
