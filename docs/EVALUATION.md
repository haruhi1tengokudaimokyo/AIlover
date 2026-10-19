# 可复现评测与实际验证边界

截至 2026-10-14，框架覆盖检索、四种对话消融、结构化记忆生命周期、语音故障及开发诊断。默认离线，不调用 LLM、Embedding、TTS 或 ASR。软件契约、真实语料本地耗时、真实角色效果是不同证据，不能混用。

## 回归与统一报告

仓库根目录 PowerShell：

```powershell
.\.venv\Scripts\python.exe backend/manage.py test web --noinput
.\.venv\Scripts\python.exe backend/manage.py check
.\.venv\Scripts\python.exe backend/manage.py makemigrations --check --dry-run
npm --prefix frontend test
npm --prefix frontend run build
.\.venv\Scripts\python.exe scripts/sync_template.py
.\.venv\Scripts\python.exe backend/manage.py evaluate_system --output-dir backend/evaluations/my-system --story-data-dir backend/story_data
```

回归使用独立测试库；对话评测用 ContextVar 数据库路由及临时 SQLite，完成后关闭连接并删除，不向应用库写评测账号/消息。输出路径已存在会拒绝覆盖。Windows 沙箱权限限制可在普通本地终端运行相同命令，不能为测试重置真实数据库。

旧登录/令牌、角色编辑、聊天、搜索/导出、记忆、备份及 ASR 测试保留。新增覆盖来源审核、CJK 短查询、Dense 故障、预算、并发/遗忘、租约恢复、迁移保留、语音取消及权限。最终测试结果见 [交付记录](PHASE4_DELIVERY.md)。前端生产构建仍有大于 500 kB 的 chunk 提示。

实际报告 [system-final/summary.json](evaluation/system-final/summary.json)：80 个用例×策略组合，失败轮数 0，15/15 项记忆状态检查通过，临时库已删除，Mock 语音文字/清理通过，外部 API 调用 0。人工相似度为空，真实质量未验证。

## 检索消融

```powershell
.\.venv\Scripts\python.exe backend/manage.py evaluate_retrieval --output backend/evaluations/my-retrieval.json
# 审核的 cases/gold ID 配合本地 bundle，不复制正文到公开 fixture。
.\.venv\Scripts\python.exe backend/manage.py evaluate_retrieval --dataset my-reviewed-cases.json --data-dir backend/story_data --dense-provider off --output backend/evaluations/my-sparse.json
# 以下明确允许真实 Embedding；需先构建匹配索引，会消耗额度。
.\.venv\Scripts\python.exe backend/manage.py evaluate_retrieval --dataset my-reviewed-cases.json --data-dir backend/story_data --dense-provider real --allow-api --output backend/evaluations/my-real-retrieval.json
```

默认 10 条 luna/nova 合成用例覆盖跨语言、关系、事实、风格、歧义、无关、路线/场景冲突及单字查询，没有伪造游戏 gold。旧策略为合成旧排序代理，Dense 为确定性 Mock。**Dense 单路评测不启用 Sparse fallback**，实际聊天仍保留故障回退。指标为 Recall@K、MRR、二元相关性 nDCG@K、无 gold 用例非空注入比例和延迟；无 gold 的前三项不进入均值。

最新 K=4 的 [retrieval.json](evaluation/system-final/retrieval.json)：

| 策略 | Recall | MRR | nDCG | 无关注入 |
| --- | ---: | ---: | ---: | ---: |
| 旧排序代理 | 1 | 0.75 | 0.813219 | 1 |
| Sparse | 1 | 1 | 1 | 0 |
| 严格 Dense Mock | 0.857143 | 0.857143 | 0.857143 | 0 |
| Hybrid Mock | 1 | 1 | 1 | 0 |

早期 `retrieval-synthetic.json` 的 Dense 含回退，仅作历史记录。小样本不能证明真实语义能力、Hybrid 优于 Sparse、剧情准确率或角色相似度。

## 真实语料本地成本及上下文检查

```powershell
.\.venv\Scripts\python.exe backend/manage.py benchmark_retrieval --data-dir backend/story_data --iterations 60 --output backend/evaluations/my-latency.json
.\.venv\Scripts\python.exe backend/manage.py preview_roleplay --slug hika --message '今天想做饭' --output backend/evaluations/my-preview.json
```

[latency.json](evaluation/system-final/latency.json) 在真实 3,272 条风格示例上执行 60 次固定料理/休息/无关 Sparse 查询：一次冷启动 348.559 ms，热 P50 3.486 ms、P95 5.2981 ms，结果数 4/4/0，无 API。只说明本机这次运行成本，无旧版对照，不是端到端聊天或质量成绩；不能拼接历史测量宣称加速百分比。

默认 `backend/story_data` 已构建。hika/ayame 安全 preview 各注入 4 条风格证据，预算 8377/16000、8229/16000；只输出 ID/计数/预算，不写 prompt/原文。Lore 仍为 0，风格召回不等于剧情理解。

## 对话消融与人工评分

```powershell
# 只验证原有 12 个用例结构。
.\.venv\Scripts\python.exe backend/manage.py evaluate_roleplay
# 12 原有 + 8 扩展，在临时库执行提取/纠错/遗忘/新证据。
.\.venv\Scripts\python.exe backend/manage.py evaluate_roleplay --offline --include-extended --variant all --output backend/evaluations/my-offline.json
# 以下会消耗配置模型额度；当前未执行。
.\.venv\Scripts\python.exe backend/manage.py evaluate_roleplay --run --include-extended --variant all --slug hika --output backend/evaluations/my-real-roleplay.json
.\.venv\Scripts\python.exe backend/manage.py score_roleplay --report backend/evaluations/my-real-roleplay.json --scores my-human-scores.json --output backend/evaluations/my-scored.json
```

同一配置/输入比较 baseline、legacy、story、story_memory，保存模型/输入/语料指纹、身份模式、预算及记忆来源版本。`story_memory` 使用真实 MemoryItem/Message/MemoryJob 生命周期，已不依赖旧摘要 fixture。每个用例独立 Friend，检查纠错、遗忘与新证据、话题及来源隔离。Offline 回复是合成占位，不能评分自然度/人设。

真实报告的 `human_dimensions` 留空。人工文件结构为 `{"scores":[{"id":"用例ID","variant":"story","dimensions":{"报告已有维度":3}}]}`；只接受已有维度有限 0..4 数字，按策略输出均值/n，拒绝给 Offline 报告评分。真实剧情准确性需要审核 facts/gold；盲评需固定模型/采样并重复运行。真实报告可能含生成正文，只保存在私有 evaluations，默认审阅打包排除。

## 语音、HTTP 与观测

`evaluate_voice --output backend/evaluations/my-voice.json` 验证 Mock 分句/时序/取消清理。生产指标包括首 token/audio、模型/TTS/队列等待/完成和清理；前端停止指标是调用清理耗时，不能当声卡停播延迟。

[http-smoke.json](evaluation/http-smoke.json) 使用 `ui_smoke_server.py` 的新隔离库及禁止外部 API 的合成服务，在真实本地 HTTP/SSE 上通过登录、偏好纠错、私有来源、停止清理、下一轮隔离、结束指标和 debug evidence。`http_smoke_test.py` 写操作前验证隔离标记，不能对应用库执行。浏览器桥接超时，**未通过按钮交互验收**。

证据面板同时要求后端 DEBUG + `ROLEPLAY_DEBUG_TRACE=true`，前端 DEV + `VITE_ROLEPLAY_DEBUG=true`。debug endpoint 按用户/Friend/generation 校验，缓存有大小/有效期限制；仅返回本轮证据，已遗忘记忆不通过旧 trace 复活。默认日志不含完整聊天、原文或密钥，无独立观测服务器。真实云语音、麦克风、网络及 EXE/WebView 尚未验收。
