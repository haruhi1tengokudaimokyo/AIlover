# AIlover 最终技术升级交付（2026-10-14）

本轮按原始任务 Phase 0→4 增量实现，保留 Django/DRF、Vue 3、LangGraph、SQLite、LanceDB；无新运行服务，无模型/语音训练。仓库开始时已有未提交修复，本次保留，不能将整个工作区差异均称为本轮新增。没有修改真实 `.env`、上传游戏资产、提交或推送代码。

## 原始要求与实现对应

| 要求 | 实际模块/交付 | 完成边界 |
| --- | --- | --- |
| A：原作上下文流水线 | `story_pipeline.py`、`build_story_data.py`、兼容旧解析/清洗脚本 | 真实 109 文件，位置/顺序/说话人/旁白邻接、来源哈希、增量/审计、人工 sidecar；未知控制流不猜测 |
| A：分离数据用途 | records、dialogue_examples、story_knowledge、voice_manifest | 风格 3272；已审核 Lore 0；音频缺失明确记录，不复制资产 |
| B：双通道 Hybrid RAG | `story_retriever.py`、`context_builder.py`、chat 接入 | Sparse/CJK 短查询、可选 LanceDB Dense/RRF、过滤/去重/空结果/回退、双身份与预算；真实语义质量未测 |
| C：结构化记忆 | `friend.py`、migration0011、`memory/structured.py`、`manage.py`、ConversationManager | 语义/约定/话题状态、来源/版本/修正/遗忘、持久任务/CAS/租约/恢复、权限隔离；提取限定明确中文句式 |
| D：编排 | `chat.py`、`graph.py`、generation lease | 读历史→取证据/记忆→构造→模型→完成落库/任务；Django 是历史事实来源，无 checkpoint 双历史 |
| E：语音与取消 | `voice.py`、`generation.py`、`orderedAudio.js`、InputField/Microphone | 句缓冲、每轮单 TTS session、限队列/有序播放、取消/晚到隔离/清理/指标；设备与云服务未验收 |
| F：评测 | retrieval/roleplay/evaluation_store、evaluate_system/score_roleplay/voice/benchmark | 四组消融、临时库真实记忆操作、来源指纹、人工评分入口；默认不付费 |
| F：证据调试 | `debug_trace.py`、chat/debug、DebugPanel | 默认关闭，仅 DEV+显式标志；当前用户/Friend/generation 权限，记忆遗忘后不泄露旧快照 |
| 兼容/数据安全 | `launcher.py`、backup/doctor、package_review、迁移核验脚本 | 启动待迁移前备份；旧命令保留；公开审阅包默认排除原作与真实模型正文 |

关系成长/情绪状态是原提示词中的可选能力，本轮不引入自动关系增长或虚构经历。云模型、Embedding、TTS、ASR 接口保留，可替换；不宣称已实现完整全双工或原作全剧情理解。

## 新数据与迁移

`0011_structured_memory` 新增 MemoryItem（类型/内容/来源/状态/版本/期限/人工标记）、MemoryChange（修正审计）、MemoryJob（状态/重试/租约），Friend 新增 epoch/floor/legacy_retired。保留原有 `Friend.memory`、revision 与 migrations；既有0010并非本轮新建。

完成消息与任务同事务保存；人工修改递增 epoch，旧/乱序任务无法覆盖；遗忘清除正文和证据，保留最小 tombstone。请求开始后发生人工修正/遗忘时，该轮任务标记失效，旧消息保留给界面但不回灌上下文或摘要。旧摘要保留且默认退役，用户重新审核后才能恢复兼容注入。

真实应用库迁移前备份：`backend/backups/ailover-20261013-205010-486117.zip`。ZIP 校验和只读逐行比较验证原账号/好友/消息/角色/用户资料旧字段一致；新增真实 MemoryItem 为 0，评测未写用户库。备份包含私人数据，禁止公开分享。

## 当前运行与回退

```powershell
# 已有应用先备份；不要删除数据库、重新 seed 或覆盖 .env。
.\.venv\Scripts\python.exe backend/manage.py backup_data
.\.venv\Scripts\python.exe backend/manage.py migrate
.\.venv\Scripts\python.exe launcher.py --doctor
.\.venv\Scripts\python.exe launcher.py
# 已有默认 backend/story_data。重建必须给新的目录，禁止覆盖旧 bundle。
.\.venv\Scripts\python.exe scripts/build_story_data.py --output extracted/story_builds/my-reviewed --previous backend/story_data --review my-review.json
$env:STORY_DATA_DIR = 'D:\AIlover\extracted\story_builds\my-reviewed'
.\.venv\Scripts\python.exe backend/manage.py build_story_index
.\.venv\Scripts\python.exe backend/manage.py process_memory_jobs --limit 100 --retry-failed
# 可独立关闭增强；不用回滚 migration 或删除数据。
$env:ROLEPLAY_RAG_MODE = 'legacy' # 或 off
$env:MEMORY_MODE = 'legacy'     # 旧摘要不会绕过退役保护
$env:TTS_SENTENCE_BUFFER = 'false'
$env:TTS_ENABLED = 'false'      # 纯文字
```

数据与索引命令详见 [DATA_PIPELINE.md](DATA_PIPELINE.md)，记忆/语音配置详见 [MEMORY.md](MEMORY.md)、[VOICE.md](VOICE.md)。真实 Dense 构建需显式 `build_story_index --dense` 并开启 `STORY_DENSE_ENABLED`，会调用所配服务；本轮未执行。桌面启动器已有迁移前备份机制，旧 EXE 不会自动包含源码升级，最终 EXE/WebView 尚未验收。

## 真实执行结果

- 最终后端完整回归 **101项通过**（28.707秒，隔离库）；包括新增人工说话人校正分类/来源追踪，测试库已销毁。
- 源码验收包随后消除旧检索测试对原作文件的依赖；解压目录完整101项通过（26.253秒），另验收筛选隐私2项通过。见review-package-validation.json和INSTALL_REVIEW.md；不是全新依赖安装结果。
- 前端 5 项播放器测试、vue-tsc 和 Vite production build 通过；大 chunk 提示仍存在。
- Django系统检查无问题，migration dry-run无变化；`git diff --check`无差异格式错误；最新生产首页模板已同步。
- 再次只读对比备份确认五类原用户记录完全一致，真实MemoryItem为0；进程核验未发现本次隔离测试Python/Vite服务仍运行。
- `system-final`：20 用例×4 策略=80 组合，失败轮数0，记忆状态15/15，临时库删除，Mock语音文字/清理通过，API调用0。
- 严格 Dense Mock 单路 Recall/MRR/nDCG=0.857143；Sparse/Hybrid Mock=1，无关注入0。仅合成契约验证。
- 真实3272风格资料60次本地Sparse：冷348.559ms，热P50 3.486ms/P95 5.2981ms，无API、无旧版对照，不宣称提速。
- 默认运行路径已建 `backend/story_data`；两个角色各注入4个风格ID的 preview 已保存。Doctor 明确模型密钥缺失、Lore0。
- 独立合成库真实HTTP/SSE验证登录、纠错/来源、取消清理、下一轮隔离、结束指标、开发证据成功。浏览器桥接超时，没有按钮操作验收。

所有指标和复现命令见 [EVALUATION.md](EVALUATION.md)、[summary.json](evaluation/system-final/summary.json)、[http-smoke.json](evaluation/http-smoke.json)。阶段1–3交付文件中的数字是当时历史结果。

## 仍需外部条件的验收

1. 人工阅读来源，提供审核 sidecar 和真实 gold。当前路线/情绪未知，Lore=0；框架不能替代剧情核验。
2. 在本机配置服务密钥，显式运行真实 LLM/Embedding 消融及人工盲评；密钥不需发送聊天。
3. 用实际云语音/麦克风/浏览器测声音、网络失败、打断和声卡延迟；当前只验证协议/Mock。
4. 重建并在 Windows EXE/WebView 验收。保留旧程序和用户数据，不把旧包验证归为新源码验证。

这些限制不影响已完成的本地流水线、记忆、取消、评测与文档；它们限制的是最终人物还原、真实语音和桌面效果结论。技术取舍与可用于简历的准确措辞见 [PROJECT_TECHNICAL_HIGHLIGHTS.md](../PROJECT_TECHNICAL_HIGHLIGHTS.md)。
