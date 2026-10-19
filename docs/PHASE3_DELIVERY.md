# Phase 3 增量交付

| 文件 | 本轮作用 |
| --- | --- |
| `views/friend/message/chat/voice.py` | SentenceBuffer/有界非阻塞队列、PacketSink 时序/序号、可替换 CloudTTSProvider |
| `views/friend/message/chat/generation.py` | 当前 generation 注册、最近完成 ID、取消、worker/stream 双完成 lease 生命周期 |
| `views/friend/message/chat/chat.py` / `urls.py` | SSE 逐轮协议、私有停止接口、超时/溢出降级、完成指标、日志脱敏与清理 |
| `views/friend/message/chat/graph.py` | RunnableLambda 同步/异步分路，聊天 ainvoke、评测 invoke、自有客户端关闭 |
| `frontend/src/js/utils/orderedAudio.js` | 顺序/去重/缺口处理、晚到回调隔离、有界缓存和资源释放 |
| `frontend/.../InputField.vue` | 新输入先停止旧轮、取消传播、播放器复用、DEV 指标与停止测量 |
| `frontend/.../Microphone.vue` | 卸载后的 VAD 销毁、ASR abort/版本保护，未做设备全双工验收 |
| `test_voice_pipeline.py` | 15 项后端分段、并行、协议 Mock、超时/取消/权限/锁与模型清理测试 |
| `frontend/tests/orderedAudio.test.mjs` / `package.json` | 5 项 Node 离线播放器测试与 npm test 入口 |
| `management/commands/evaluate_voice.py` / `docs/evaluation/voice-mock.json` | 不写数据库、不调用 API 的显式 Mock 语音消融和测量 |
| `.env.example` / `docs/VOICE.md` / 现有开发文档 | 可回退配置、运行命令、真实边界与验证结果 |

全部 85 项后端测试通过，前端 5 项测试与 production build/type-check 通过；无新增 migration，schema 检查无缺失变化。没有修改真实 `.env`、写真实聊天、训练/部署语音模型或消耗 API。Vite 仍有大 chunk 提示。

仅完成本地工程与离线验证。真实 API Key 缺失，云端 TTS/模型效果、麦克风回声/VAD、网络断开时序、Windows EXE/WebView/MSE 均未实际验收。下一阶段是统一综合评测与真实资源条件下的人工审核，不能提前写效果提升成绩。
