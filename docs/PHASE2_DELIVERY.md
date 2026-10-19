# Phase 2 增量交付清单

| 文件 | 作用 |
| --- | --- |
| `web/models/friend.py` / `migrations/0011_structured_memory.py` | 新增记忆条目、变更、任务以及 Friend epoch/floor/retired 字段；保留旧列 |
| `views/friend/message/memory/structured.py` | 保守提取、来源水位、去重/冲突、人工操作、遗忘、租约、重试、检索 |
| `management/commands/process_memory_jobs.py` | 崩溃后任务恢复与显式失败重试，不调用 API |
| `views/friend/message/chat/chat.py` / `documents/utils/context_builder.py` | 完成消息与任务原子保存、结构化记忆注入、遗忘历史边界、来源 trace |
| `views/friend/message/manage.py` / `urls.py` | 私有条目/来源 CRUD、开关、旧摘要明确恢复、清空与导出兼容 |
| `views/friend/message/memory/update.py` | 防止已退出使用的旧摘要被后台旧任务恢复 |
| `frontend/.../ConversationManager.vue` | 新增逐条记忆、来源、修改、忘记、新增和审核旧摘要恢复 |
| `management/commands/doctor.py` / `.env.example` | 模式和任务诊断、默认结构化配置与回退 |
| `test_memory.py` / `test_memory_concurrency.py` / `test_memory_migrations.py` | 新增 26 项规则、生命周期、竞争、迁移和聊天集成测试 |
| `scripts/verify_memory_migration.py` | 只读比对备份的旧字段与迁移后数据库，不输出用户内容 |
| `docs/MEMORY.md` 及架构/评测/路线/技术亮点/README | 更新真实实现、运行命令、结果与尚未验证边界 |

本机先创建并校验 `backend/backups/ailover-20261013-205010-486117.zip`，只应用 `web.0011_structured_memory`。只读核验旧 auth_user / Friend / Message / Character / UserProfile 完整行与备份一致。没有向真实记录写合成消息或测试记忆；新增表仍为空。

真实执行：全部 70 项测试通过，新增模块单独 26 项通过；前端 type-check / Vite build 通过（已有大 chunk 提示）；Django check 无问题；makemigrations dry-run 无缺失变化。未调用真实 LLM/Embedding/TTS/ASR。

默认结构化路径可运行，不依赖付费提取模型；目前只识别明确称呼、限定饮食偏好、提出的约定和待续话题。通用 LLM 提取、任意偏好语义合并、关系成长和真实模型记忆使用质量没有完成。语音阶段尚未进入，本轮不宣称全双工或语音性能提升。
