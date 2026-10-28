# 四角色夜间训练与回传

云端连接参数仅放在被Git忽略的 `runtime/cloud-connection.json`，字段为 `host`（如 `root@your-host`）、`port`、`key`（私钥文件路径，不能写私钥内容）。也可通过 `AILOVER_SSH_HOST`、`AILOVER_SSH_PORT`、`AILOVER_SSH_KEY` 覆盖；仓库不包含实际连接地址或密钥。

用户已明确授权：麦、萤、绯华、菖蒲各自文本与语音训练，自动接续、保存本机，所有产物回传成功后关闭此AutoDL实例。禁止释放实例、删除源数据、另租服务器。

## 实际启用的程序

- 云端 `screen ailover-overnight`：`run_overnight.py`，等待原麦/萤正式训练队列结束，不打断进行中的任务。随后四角色新版文本串行训练，再用每角色完整语音训练区串行完成官方特征提取、S2与S1训练。
- 本机 `overnight_local.py`：补传绯华、菖蒲四个包；每分钟查询产物清单，逐包下载、验证SHA256与ZIP CRC。临时阻止系统自动睡眠，允许屏幕关闭；退出时恢复防睡眠请求。
- 本聊天每15分钟监督一次：检查真实日志、处理失败、继续尚未完成的步骤。安静时不通知。
- 云端 `finalize_shutdown.py`：必须核对四角色八份新模型、共用底模、所有已登记成果以及本机完整回传确认，才调用AutoDL的关机命令。不执行实例释放。

本机结果目录：`D:\AIlover\训练成果\AutoDL_四角色`。其中 `本地进度.json`、`自动回传.log` 为真实状态。云端 `/root/autodl-tmp/ailover/reports/overnight-status.json`、`overnight-artifacts.json` 与 `logs/overnight.log` 为接续状态。

## 参考项目与本轮选择

1. ChatHaruhi：角色背景、真实台词、带上下文的角色回复是重点。保持V3的原作上下文和说话人身份，不把旁白、他人隐私想法或未审核生成候选塞进监督回复。参考：https://github.com/LC1332/Chat-Haruhi-Suzumiya
2. LLaMA-Factory/PEFT：采用同类SFT与全attention/MLP线性投影LoRA方法，本轮选择rank32、alpha64、dropout0.05、4-bit NF4、BF16计算、学习率3e-5、4轮、有效batch8、cosine和5%预热。按验证loss选检查点。rank32是本项目的较高容量候选，不是引用项目给出的最优参数，更不能保证胜过rank8。参考：https://llamafactory.readthedocs.io/en/latest/advanced/arguments.html
3. GPT-SoVITS：固定官方提交b4570b876f5c086819ba84e3215472733c6a7b70。使用v2Pro说话人特征与S1/S2完整适配，保留预训练量化编码器冻结设置。完整train清单，batch4、S2=12轮、S1=15轮、每3轮保存推理权重。完整数据不缩为15分钟。参考：https://github.com/RVC-Boss/GPT-SoVITS

不重复下载新的文本底模；本轮使用已下载且已实际跑通的Qwen2.5-7B-Instruct。更大模型需要独立对比，不能把“高规格”简单等同于更大权重或无限增加训练轮数。

## 全部数据的含义

全部符合V3规范的文本训练区、全部合格语音训练区都会提交给相应训练器。原始素材、验证集、测试集、参考音频和已有排除项仍保留各自用途，不混入训练。待审核24条生成候选不冒充真实审核通过数据。

上游语音加载器另有时长、音素转换、音素/semantic比率限制。`audit_speech_runtime.py` 记录每阶段实际纳入与排除ID，输出 `runtime-membership.json`；特征缺失则显式停止，不静默丢掉失败条目。不能用解除上游质量限制的方式虚报全部可训练。

日语录音配日语标签；无真实中文录音。中文语音依靠多语种底模的跨语言能力。所有语音检查点保留供后续中文听评，不能声称最后一轮音色最好。上游S1/S2未自动对独立验证集评分，此局限明确写入结果；没有伪造MOS、相似度或人工听评。

## 失败处理与恢复

失败不会执行成功关机。日志、完成模型及原始材料保留，监督任务继续处理。`run_overnight.py` 复用既有job ID、已打包产物和完成记录，文本有检查点时尝试resume；语音沿用上游断点逻辑。不要同时启动多个同名队列。

本机如果断网、关机或回传校验失败，云端不能凭空确认文件已保存，不会执行成功关机。不要关闭本机、AutoDL实例或断开网络直到回传完成；关闭浏览器本身不影响训练。

关机请求成功不等同于已经确认控制台状态；监督任务需继续确认实例是否关闭。没有AutoDL控制台查询凭证时，应如实记录“已请求关机”，不能只凭SSH断开宣称平台已停止计费。
