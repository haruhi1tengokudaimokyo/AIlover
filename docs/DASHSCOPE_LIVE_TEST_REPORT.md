# 百炼四角色文本模型接入验收：2026-10-28

四个部署 Code 均完成真实 DashScope 请求，以及项目 LangGraph → DashScope Provider 的真实流式调用。Key 只保存在被 Git 忽略的 backend/.env；本报告不包含凭据。

|角色|实际部署 Code|HTTP|流式块数|结果|
|---|---|---|---|---|
|hika|qwen2.5-7b-instruct-974feb886208|200|9|成功|
|ayame|qwen2.5-7b-instruct-8420bd41b30b|200|12|成功|
|hotaru|qwen2.5-7b-instruct-475355645709|200|9|成功|
|mugi|qwen2.5-7b-instruct-6f0c05ddbbd4|200|8|成功|

第一轮普通 HTTP 问候测试合计 105 Token（输入80、输出25）；另进行了四次项目流式短问答。流式轮未采集 usage，不能把105当成本轮所有请求总量。实际费用以平台账单为准。

启用配置：runtime/cloud/manifest.bailian.live.json；backend/.env 已设置 CHARACTER_MODELS_ENABLED=true 及上述清单路径。新启动或重启后端后加载；已在新 Django 进程验证四角色路由实际解析一致。本次没有控制已有后端进程重启，也没有声称浏览器端到端 UI 已验收。

语音托管尚未完成，四角色暂配置 tts_provider=disabled，SSE 的 audio_enabled 正确为 false，不会访问已关闭的本地 GPU 接口，也不会冒用通用音色为训练音色。原本地及远程语音适配实现保留。

最终后端完整141项回归通过；新增文本独立于语音的路由用例。真实短问答仅证明可调用、流式回调和模型路由，尚未验证人格质量、长对话、多用户负载和中文训练音色。

原始记录：runtime/cloud/dashscope-live-results.json、runtime/cloud/dashscope-graph-live-results.json；回归日志 runtime/bailian-backend-tests.log。

之前的四个 offline 导入 ID 请求均返回 Model not exist；本次改用用户在部署页取得的模型Code后成功。无需重新导入或训练。

百炼运行在云端：关闭控制台网页、退出账号或本机关机，不会因此下线部署。按 Token 用量计费，没有调用就没有该部署的推理 Token 费用；OSS 等存储独立计费。官方说明一个月未使用会自动释放按 Token 部署。

[官方 Token 部署与计费](https://help.aliyun.com/en/model-studio/model-deployment-token)

回滚：将后端 CHARACTER_MODELS_ENABLED=false 后重启，或恢复 runtime/cloud/activation-previous.json 中的原开关和清单路径。不要删除权重、数据库或用户数据。
