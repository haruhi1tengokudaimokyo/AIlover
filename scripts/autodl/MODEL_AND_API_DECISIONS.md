# AIlover 模型与服务决策

当前 Qwen2.5-7B-Instruct 是兼容性稳定的首轮基线，不能视为最终产品效果上限。原始权重约15GB；4-bit量化权重大小与完整下载大小不同，实际运行还需要激活、KV cache、适配器和框架开销。

建议下一候选为 Qwen3.5-9B，半精度权重粗估18GB。它需要更新的独立运行/训练栈和对应模型加载、模板处理，不能直接替换当前固定 Transformers 4.51.3 的模型目录。当前没有启动这个候选的下载或训练。24GB卡是否容纳某个配置必须实际短测，不能仅用权重大小担保。

当前文本训练：SFT + 4-bit NF4 double-quant QLoRA，BF16计算；PEFT LoRA rank8、alpha16、dropout0.05，attention及MLP七类线性投影；学习率5e-5，两轮。每个角色独立适配器。只计算助手回复loss，维持原始分组划分，验证集选检查点，测试集不参与选点，记录实际训练前后回复。

这些参数是有限语料上的保守起点。麦454条、萤1067条正式训练样本，原作短句不能覆盖所有现实聊天。模型更新、参数增大、训练轮数增加均不保证角色还原更好。候选模型需使用相同数据划分和预先固定的开发评估集比较；最终测试集不用于反复调参。

## API 服务

微调后的开源模型可自托管为 HTTP API。vLLM 支持兼容 `/v1/chat/completions` 的服务及多个 LoRA，客户端用不同 model 名选择麦或萤。适配器必须加载到训练时匹配的同一基础模型，不同基础模型之间不能直接复用。

现有后端 `backend/web/views/friend/message/chat/graph.py` 已读取 `API_BASE`、`API_KEY` 和全局 `MODEL`。因此有接口接入基础，但当前尚无按角色选择模型的正式路由，不能声称只更改地址就完成多角色部署。它还会绑定工具；上线前需检验适配器的工具调用兼容性，或把工具/记忆整理与角色回复分层。

建议职责：应用后端管理鉴权、角色、会话、用户隔离的长期记忆与工具 → 文本推理API按角色加载适配器 → 独立GPT-SoVITS服务生成中文语音 → 前端流式显示/播放。用户记忆不写进共享角色权重。训练与在线服务在单卡上争抢显存，应分时或独立部署。

“购买现成API”与“托管自己的微调权重”不同：前者可增强通用能力，但不会自动拥有本地LoRA；后者需平台支持匹配基础模型、适配器和推理运行时。此处没有购买或调用付费API，也没有开放未鉴权的公网推理服务。

参考：

- https://huggingface.co/Qwen/Qwen3.5-9B
- https://docs.vllm.ai/en/stable/features/lora/
- https://huggingface.co/docs/peft/v0.15.0/developer_guides/quantization
- https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
