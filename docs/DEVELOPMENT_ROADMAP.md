# 开发路线与继续执行入口

2026-10-14：Phase1–4本地工程实现与结果见 [最终交付](PHASE4_DELIVERY.md)。以下初始路线保留为设计依据，其中未来阶段表述不代表当前待办。剩余验收依次为人工原作facts/路线/gold审核、真实模型/Embedding阈值与盲评、云语音/设备/浏览器/新EXE。当前缺密钥且Lore0；通用语义提取、情绪/关系成长和完整引擎路径求值均为可选后续，不开展训练或新增服务。

## Phase 1：本轮交付

已实现并离线验证：保守 KAG 解析、来源/条件/上下文、独立数据集、人工 sidecar、哈希拒绝过期审核、按文件增量构建与原子发布；Lore / Style 双通道、Sparse posting lists、可选 LanceDB Dense、RRF、去重/限额/过滤/故障降级；独立 Context Builder、身份模式、预算和回退；合成消融指标、实际本地延迟、对话消融入口、基础开发 trace。

仍需人工资源：解释 KAG 自定义控制宏和跨文件路径；核对未知 speaker / 角色别名；审核 Lore；建立真实游戏 gold 检索样本；匹配 Embedding 模型/维度并校准门限；真实 LLM 盲评。当前风格示例是原文邻接参考，不是人工验证的全剧情对话。未开展训练、权重优化或语音克隆。

## Phase 2：结构化长期记忆

已完成并运行：MemoryItem / MemoryChange / MemoryJob、来源与版本、冲突/纠正/忘记水位、持久租约和有上限重试、接口与管理界面、上下文集成、迁移和备份验证。见 [MEMORY.md](MEMORY.md)。以下原计划作为设计背景；自动提取目前采用保守规则，通用模型提取与关系成长仍未实施。

入口代码：`web/models/friend.py`、`web/views/friend/message/memory/update.py`、`web/views/friend/message/manage.py`、前端 `ConversationManager.vue`。

下一轮先完成设计评审与备份，再以 Django migration 增加 MemoryItem、MemoryRevision 和持久 PendingMemoryJob。语义/事件/会话状态分开，绑定 User / Friend / Character、源 Message ID、状态/版本、有效期和人工更改。旧摘要保留为 legacy reference，不把无来源句子转成高置信事实。

记忆新增/修改/忘记在短事务中执行，后台工作携带 expected revision 与消息水位。删除/清空必须产生 tombstone 或失效边界，防止旧任务/旧摘要恢复内容。用户纠正优先，模型提取只接受用户消息证据。任务落库后可由管理命令恢复处理，不能依赖 daemon thread。继续复用原有开关、乐观锁与权限界面。

验收已通过：跨用户/角色隔离、偏好替换、人工纠错、忘记不恢复、双线程竞争、清空聊天、过期租约恢复和旧摘要迁移保留。真实模型使用记忆的质量仍未验证，保守规则覆盖面有限。

## Phase 3：实时语音

已完成本地工程实现与离线验证：分句/尾句、有界语音队列、可替换云端 provider、generation/音频序号、私有取消接口、模型异步取消、自有客户端关闭和播放器回调隔离。85 项后端、5 项播放器测试通过，见 [VOICE.md](VOICE.md)。下方原设计要求中，真实声学/云服务验收仍未执行。

入口代码：`chat.py` 的 stream_model / stream_voice / run_tasks / event_stream、`InputField.vue` 的 processId / audioQueue / MediaSource。

设计句子缓冲、可替换 TTS provider、顺序号队列、统一 generation ID 与取消 token。文本生产不能被音频消费阻塞；客户端停止、SSE 断开、组件卸载都传播到同一 generation；清除晚到内容与所有旧播放器回调。现有单一云端 TTS session 可复用，但先验证 provider 的分句行为，不能对每 token 创建任务。

Mock 场景包括乱序音频完成、超时、音频失败仍可文字、连续新输入、重复停止、断线、队列背压、资源清理。真实测量 TTFT/TTFA、总耗时、音频等待及停止播放延迟。完整 VAD/全双工只有在设备与协议验证后再开展。

## Phase 4：综合评测与开发面板

入口：`evaluate_roleplay`、`evaluate_retrieval`、`benchmark_retrieval` 与前端 DEV diagnostics。

增加真实模型与真实 Dense provider 的固定配置和多次运行；人工审核真实 gold 并将 source_id/哈希绑定评测版本。补齐事实准确性、缺证据编造、身份、记忆生命周期、中文自然度和人工角色相似度盲评。将 trace 扩充 provider 耗时、TTS 排队和取消结果；用当前用户/好友权限提供源消息与记忆条目查看。默认不启用独立监控服务。

## 参考项目与设计取舍

- [SillyTavern](https://github.com/SillyTavern/SillyTavern) / [World Info](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)：按角色与当前关键词激活资料、预算受控；采用相关资料注入，不移植整个应用。
- [Letta](https://github.com/letta-ai/letta) / [Mem0](https://github.com/mem0ai/mem0)：参考状态与记忆生命周期；轻量迁移留到 Phase 2，不安装平台服务。
- [Graphiti](https://github.com/getzep/graphiti)：参考来源与时间/关系区分；当前原文不能可靠支撑自动图谱，暂不引入图数据库。
- [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)：参考语音交互与打断需求，Phase 3 对齐本项目协议，当前不移植 Live2D/模型部署。
- [Arize Phoenix](https://github.com/Arize-ai/phoenix)：参考 trace 与评测结构；采用本地脱敏 JSON，不启动监控服务器。
- [promptfoo](https://github.com/promptfoo/promptfoo)：参考固定输入与策略对比；复用 Django 命令与 Python 测试，默认不消耗 API。
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：checkpoint 会形成图执行状态；当前以 Django 数据作为历史事实来源，不增加第二套需要协调的聊天历史。

上述资料在开发前已查阅。这里列的是设计依据和后续方向，不表示这些开源项目作为依赖已集成。
