# Phase 2：结构化长期记忆

已实现轻量 SQLite 记忆生命周期与前端管理，不依赖模型服务、GPU、Redis/Celery 或无限后台线程。默认 `MEMORY_MODE=structured`，旧路径可通过 `legacy` 回退。新 schema 需要 migration `0011_structured_memory`；不会把旧摘要自动转换为未经来源验证的事实。

## 存储与证据

- Friend 新增 memory_epoch（任务失效边界）、memory_floor（旧消息处理/模型上下文边界）和 memory_legacy_retired（旧摘要退出注入标记），继续使用 memory_revision 做乐观锁。
- MemoryItem 通过 Friend 归属当前 User / Character，含 kind、canonical key、JSON content、status、version、来源 Message FK、证据水位、忘记水位、人工标记、置信字段、有效期和时间。
- MemoryChange 记录创建/更新/纠正/人工编辑，保留来源与 actor；遗忘时清除旧内容和来源，只留操作元数据。
- MemoryJob 与完成的 Message 在同一事务落库，含 epoch、状态、租约 token/到期、重试次数、重试时间和不含正文的错误类型。

语义、事件/约定、待续会话状态分开；relationship 类型留出模型能力，但不自动创建恋爱状态或关系成长。游戏 Lore 不受这些写入接口影响。来源查看返回用户消息，不返回内部 prompt 或角色推测。

## 提取与更新

默认提取器只接受完整、明确的中文用户语句：称呼（叫我/我叫/我的名字是）、限定饮食偏好（咖啡、茶、奶茶、牛奶、甜食、辣食、辣椒）、约定和下次/稍后待续话题。问题、假设、引号和嵌入指令不作事实提取。不读取 assistant.output 或旧摘要。支持“我喜欢咖啡” → “我现在/其实不喝咖啡了”替换同一条当前偏好，以及称呼纠正。

这是保守规则实现，覆盖面有限，不是通用自然语言记忆理解。约定存为“用户提出约定”，不推断双方已经确认。自动 state 有 7 天有效期，再次明确提出会续期。confidence=1 仅表示规则完整匹配，不代表事实真伪概率。

同一 key 仅一条当前记录。乱序任务比较 source ID，旧任务不能覆盖新事实；重复事实不增版本，但推进证据水位。人工编辑受保护，普通重复提取不覆盖；明确更正/现在/其实等新用户纠正可以更新。手动新增以类型/文本摘要去重，源 actor 为 manual。

## 并发与恢复

每个任务以 CAS 获取 60 秒租约；只有当前未到期 token 可以提交。自动写入在短事务中 CAS Friend revision，条目/审计/job done 同步提交。SQLite 锁竞争留下可恢复任务；不能使用 select_for_update 当作 SQLite 行锁保证。

人工操作增加 epoch 并取消旧 pending/running/failed 任务。清空聊天会清空摘要、禁用记忆、擦除条目内容、删除消息及关联任务。忘记单条记忆会保留最小 tombstone，并退出旧摘要注入；聊天记录仍在 UI 可见，但模型不再读取遗忘边界之前的历史。这会减少近期对话连续性，是为避免模型从旧窗口重新引用忘记事实而采取的保守取舍。其他有效结构化条目继续保留。

新消息中的明确事实可以重新建立被忘记的 key；旧任务、旧消息和旧摘要不能自行恢复它。旧摘要原文仍保留供查看/审核，切回 legacy 不自动恢复。用户明确点击“使用审核后的摘要”并提交当前 revision 才会重新允许旧模式注入。

新完成消息先持久化任务，再执行快速本地规则；工作失败不丢完成消息。崩溃后的 pending/过期 running 可用命令恢复，最多自动尝试 3 次，达到上限需人工重试。没有部署常驻队列服务；空闲时不会自行轮询失败任务。

```powershell
.\.venv\Scripts\python.exe backend/manage.py process_memory_jobs --limit 100
# 修复故障后，显式重试达到上限的任务；仍校验 epoch 与来源水位。
.\.venv\Scripts\python.exe backend/manage.py process_memory_jobs --retry-failed --limit 100
```

## 接口、界面和上下文

保留 `/api/friend/memory/` 摘要/开关接口。新增 `/items/` GET/POST/PATCH/DELETE 和 `/source/` GET，全部按当前用户/好友查询，版本冲突返回 409。列表有分页，来源只返回该好友消息，导出增加 structured_memories。现有 ConversationManager 增加条目编辑、新增、忘记与来源查看，不重写聊天体验。

关闭记忆同时关闭提取和注入。Context Builder 接受独立 memories 列表，包含条目 ID、kind、版本、source_message_id，受原有预算和去重限制。旧摘要不会混入结构化模式；模型历史继续使用 Django Message，未增加 LangGraph checkpoint 历史。

## 迁移、备份和回退

本机已先备份到 `backend/backups/ailover-20261013-205010-486117.zip`，校验 ZIP 完整，再应用 `0011`。备份包含敏感账号/聊天数据，只保存在被忽略的本地目录。本轮没有向真实用户记录写入测试记忆或消息。

其他环境先关闭应用并执行：

```powershell
.\.venv\Scripts\python.exe backend/manage.py backup_data
.\.venv\Scripts\python.exe backend/manage.py migrate web 0011_structured_memory --noinput
$env:MEMORY_MODE = 'structured'
.\.venv\Scripts\python.exe backend/manage.py runserver
```

`scripts/verify_memory_migration.py --backup <zip> --database <db>` 只读逐行比较备份中的旧字段；若迁移后又有正常聊天写入，不应把不一致直接当作迁移丢失。不会打印用户内容。

回退只切 `MEMORY_MODE=legacy`，保留新增表；不要逆向 migration 丢掉结构化数据。退出使用的旧摘要需要用户重新审核才可注入。EXE 需重新打包与实际运行验证，本轮只验证前端构建和 Python/数据库链路。

## 验证与剩余边界

最终共 70 项离线测试通过，其中本阶段新增 26 项；前端 type-check 与生产构建通过，仍有大 chunk 提示。只读逐行核验确认本机 auth_user、Friend、Message、Character、UserProfile 的全部旧字段与迁移前备份一致，新 MemoryItem 为 0，没有写入真实测试数据。

测试覆盖规则拒绝推测、事实冲突、乱序/重复水位、用户纠正、遗忘擦除/旧摘要隔离、源消息权限、跨角色隔离、旧任务/租约、失败重试、清空、真实双线程 SQLite 竞争、迁移前后旧记录保留、完成消息持久任务与上下文注入。命令：`python backend/manage.py test web --noinput`。

尚未实现通用 LLM 提取、任意偏好语义合并、记忆语义向量检索或关系成长；真实模型对记忆的使用质量未调用 API 验证。原有 legacy 摘要回退仍是旧线程路径，结构化默认路径使用持久任务；不能宣称旧摘要架构也已获得相同崩溃保障。
