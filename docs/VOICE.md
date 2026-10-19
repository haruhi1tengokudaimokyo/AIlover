# Phase 3：可取消的流式语音

保留现有云端 TTS/ASR 与 SSE，不训练、克隆、部署本地语音模型。本阶段实现分句缓冲、有序播放和取消传播；真实云端性能、音频质量与实际麦克风/Windows WebView 行为仍未验证。

## 流水线与模块

`LLM token → SentenceBuffer → bounded SentenceQueue → CloudTTSProvider → generation/audio_seq SSE → OrderedAudioPlayer`

`voice.py` 分离句子缓冲、队列、生产侧 PacketSink 和 TTS provider。默认 minimum=4、maximum=80 字符；中文句号/问叹号/分号/换行及长度限制触发分段，最后尾句会 flush。文字包立即进入 SSE，不等待 TTS。当前短于最小长度的句子会与后续文字合并，最大长度不是精确语义切分，需真实服务校准延迟与自然度。

云端保持每轮一个 WebSocket/task，sender 和 receiver 并行；原实现也不是每 token 新建 WebSocket，本轮减少的是 continue-task 的粒度。TTSProvider 接口为 `async stream(sentence_queue, emit_packet, voice)`，允许以后换本地 provider；本轮不安装本地模型。

队列默认最多 32 句，offer/finish 使用非阻塞写入。溢出只取消语音任务，继续文字；TTS 失败/启动超时/总超时同样保留文字。WebSocket open=10s、启动事件=10s、recv=30s、close=2s，TTS 总超时默认 90s，整个生成延续原 120s 上限。结束时 await 取消子任务并清空句子队列。

## generation 与停止协议

前端为每轮生成 UUID，提交 `generation_id`；旧客户端未提供时后端生成。SSE 起始 event 与每个 JSON 包携带同一 ID，音频从 0 编号 audio_seq。传统 `[DONE]` 标记继续保留，前端用当前请求闭包/AbortController 隔离它。近期完成 ID 的重复使用会被拒绝，避免迟到取消命中新轮。

`POST /api/friend/message/chat/cancel/` 要求登录、当前用户拥有 Friend，并匹配该好友当前 generation。错误或旧 generation 不取消新轮，重复停止无害。客户端先立即暂停播放器/清队列、abort SSE，再请求后端取消；下一轮输入等待已有取消请求。服务端若仍清理资源，会继续保持好友 lease，拒绝同好友重叠写入。停止请求等待最多 .5s 返回 cleanup 状态，客户端可作有界重试。

generation 内记录 stop / worker_done / stream_closed。只有模型/TTS 协作任务结束且流的消息保存/关闭结束后，才释放 lease 与删除活动注册。关闭未开始的响应也能释放；worker 无法启动则返回错误并清理。取消轮不保存部分回复或触发记忆任务；生成已完成后的正常消息仍按原事务保存。

LangGraph agent 通过 RunnableLambda 保留同步 invoke 评测和异步 ainvoke 聊天路径，避免主模型请求隐藏在不能强制取消的同步 executor 中。每轮关闭自有 AsyncOpenAI/OpenAI 客户端；关闭失败记录错误并标注 cleanup_complete=false。真实 SDK/服务网络条件仍需验证，不能用 Mock 冒充端到端清理成绩。

注册表与 lease 是本地单进程状态，适合当前桌面 waitress 多线程服务，不支持多进程/分布式部署的跨进程停止。不会创建第二套聊天历史，也没有新数据库 migration。

HTTP 实际断网的关闭检测由 WSGI/网络决定，静默等待时仍有 10s SSE heartbeat；显式停止接口减少对下一次写 socket 的依赖。不能把离线 generator.close 测试等同于全部真实网络条件已验收。异步 provider 必须配合 cancellation；不能强制杀死不合作的 Python/SDK 阻塞调用，lease 会保护后续写入。

## 前端有序播放与资源

`OrderedAudioPlayer` 将每个 sourceopen/updateend 回调绑定到自己的 generation / MediaSource / SourceBuffer。旧回调直接忽略；audio_seq 去重、缓存乱序并按序 append，finish 检出缺口，损坏数据和播放异常降级为文字。前端最多缓存 128 段/4 MiB，避免队列无限增长。

停止使 generation 失效，然后 pause、清队列、abort 更新中的 buffer、撤销 object URL、解除 Audio src 并 load。新输入、关闭和组件卸载走同一路径。正常结束后的 URL 保留以便音频继续播放，到下一轮/停止/卸载时释放；服务端 DONE 不代表耳机已播放完。

Microphone 增加卸载标识和 ASR 请求版本：初始化晚到时销毁 VAD，卸载/新录音取消旧 ASR，晚到识别不再发送新聊天。已有 VAD speechStart 会触发停止，但未测试真实设备回声/误触发/声学延迟，不能宣称可靠全双工语音。

## 指标与日志

生产侧记录 TTFT/TTFA、model_ms、tts_ms；queue_wait_count/total/max 表示句子从入队到 provider sender 消费的等待，**不是**云端合成或前端播放排队时间。complete_ms 是生成创建到该轮流处理与工作资源完成。audio_chunks 是产生的传输片段数，sentence_count 是入队数；errors 仅含阶段代码。cancelled / cleanup_complete 记录结果。

SSE 完成包向当前用户返回 metrics；停止接口返回当前快照，DEV 面板合并显示。前端 stop_playback_ms 用 performance.now 测 pause/清理调用耗时，不是声卡尾音消失时间。日志只含 generation ID、错误类型和这些数字，不含完整聊天、原作文本、音频或密钥。真实浏览器/服务的数值必须在用户配置 API 后实测，本轮没有真实性能提升数字。

## 配置与回退

```powershell
# 不需要新的数据库迁移。沿用现有 API/TTS 配置。
$env:TTS_SENTENCE_BUFFER = 'true'
$env:TTS_SENTENCE_MIN = '4'
$env:TTS_SENTENCE_MAX = '80'
$env:TTS_QUEUE_LIMIT = '32'
$env:TTS_TIMEOUT_SECONDS = '90'
# 分句回退：仍保留 generation 隔离和有界队列。
$env:TTS_SENTENCE_BUFFER = 'false'
# 完全关闭云端语音，继续文字。
$env:TTS_ENABLED = 'false'
```

本机目前没有真实模型 API Key，无法验证真实聊天或云端语音；没有修改用户 `.env`、训练模型或消耗付费调用。Windows EXE 需要重新打包、实际 WebView/MSE 验证后才算桌面验收。

## 复现验证

```powershell
.\.venv\Scripts\python.exe backend/manage.py test web --noinput
.\.venv\Scripts\python.exe backend/manage.py evaluate_voice --output backend/evaluations/my-voice-mock.json
cd frontend
npm test
npm run build
```

后端新增 15 项测试：字符到句子/尾句、队列有界、文字与 TTS 并行、模型/语音取消、无 orphan asyncio task、超时/溢出、云端协议 Mock 与 socket 释放、停止权限、旧 ID、lease 时序、SSE 序号/指标、断线不落部分消息、worker 启动失败释放、LangGraph 同步/异步分路、模型请求取消和客户端关闭。前端 5 项测试：乱序/重复、晚到 sourceopen/updateend、重复停止/URL/buffer 清理、缺口/损坏/溢出、浏览器不支持时文字降级。

`docs/evaluation/voice-mock.json` 标明 synthetic、real_audio=false、api_calls=0；固定合成文本下，token 转发产生 18 个 continue 输入，分句产生 2 个。两种输出文字完整、资源清理通过。Mock sleep 的 TTFA/总时间受 Windows 调度影响，不能拿它证明云端低延迟、音质提升或少用了 16 次模型任务。

最终验证：85 项后端离线测试通过，前端 5 项离线播放器测试通过，Vue type-check 和 Vite 生产构建通过（仍有大 chunk 提示）；makemigrations 检查无新变化。真实 LLM/TTS/ASR 未调用，没有新增真实聊天或记忆记录。
