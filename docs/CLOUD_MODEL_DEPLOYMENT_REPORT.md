# AIlover 四角色模型云端托管与 API 接入报告

> 后续更新：四个文本模型已完成百炼部署、真实 API 与 LangGraph 流式验收并写入本机后端配置，详见 [最新验收记录](DASHSCOPE_LIVE_TEST_REPORT.md)。下文保留最初准备阶段的状态；语音和 Docker/GPU 验收仍未完成。

检查日期：2026-10-28。此报告记录本机实物检查与本地实现；没有开机 AutoDL、创建付费资源、上传模型或发送真实平台推理请求。

## 1. 当前结论与边界

四份文本 Adapter 均符合目前能够在本地验证的百炼 LoRA 文件要求，已经各自生成最小 OSS 目录。它们是**可以提交导入校验的候选模型**，不能据此宣称百炼已经接受。四份模型的不可变上游 revision 缺失，平台实际底模版本及外部导入模型的按 Token 部署资格也尚未确认。

|角色|本地格式检查|百炼实际导入|按 Token 部署资格|真实 API 调用|
|---|---|---|---|---|
|Hika 绯华|通过，候选|未执行|未确认|未执行|
|Ayame 菖蒲|通过，候选|未执行|未确认|未执行|
|Mugi 麦|通过，候选|未执行|未确认|未执行|
|Hotaru 水无月萤|通过，候选|未执行|未确认|未执行|

文本暂没有哪位角色被证明“必须用自定义 GPU”；如果控制台拒绝底模、配置或部署资格，使用已准备的 vLLM 四 Adapter 备选。GPT-SoVITS 四角色权重需要自定义语音推理环境，本次准备的是一个 RunPod 队列 Worker。

**训练完成、文件完整、接口 Mock 通过，都不等于中文对话质量或中文音色通过了真实模型验收。**

## 2. 检查依据和实际文件

原训练成果保留在 `D:\AIlover\训练成果\AutoDL_四角色\`。历史完整回传记录为该目录的 `完整回传确认.json`；11 个归档总计 23,660,898,607 字节。本次复用已安装的 `D:\AIlover\runtime\` 文件，没有重训、修改权重或重新打包全部训练资料。

本次逐角色机器检查、底模及 Adapter 每个文件的 SHA256（上传清单自身的哈希另见 docs/CLOUD_UPLOAD_MANIFESTS.json）：

- `D:\AIlover\runtime\cloud\compatibility.json`
- 可纳入 Git 的检查快照：`D:\AIlover\docs\CLOUD_MODEL_COMPATIBILITY.json`
- 导出目录重新校验结果：`D:\AIlover\runtime\cloud\verification.json`

四份 Adapter 共用同一实际底模：`Qwen/Qwen2.5-7B-Instruct`，训练记录路径 `/root/autodl-tmp/ailover/models/Qwen2.5-7B-Instruct`。下载来源为 ModelScope；原下载未指定不可变 revision，`.mv` 只记录 `Revision:master,CreatedAt:1740591936`，Adapter 的 `revision` 为 null。无法从这些记录恢复可信的 Git commit，不能伪造为某个 Hugging Face SHA。

底模 `config.json` 的 SHA256：`7463bb0ea78315365e6c6b74de4e73bbcc8359dfb0c5a737584e077d42c0b03c`。完整底模四个权重分片的哈希见检查 JSON。自定义推理方案复用本机这份底模，而不是重新下载一个可能已经变化的 master。

四份共同配置：标准 PEFT `LORA / CAUSAL_LM`；rank 32、alpha 64、dropout 0.05；28 层，392 个 A/B 张量；target modules 为 `q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj`。无 DoRA、rsLoRA、可训练额外模块或视觉权重，无分层 rank/alpha 变化，bias=none。检查了张量形状、A/B 配对、数据偏移和数据字节长度。

词表、added tokens、归一化/切词/解码流程和 chat template 均未改变。tokenizer 的原始 JSON 与 merges.txt 字节不完全相同，是 tokenizers 序列化差异；归一化成 BPE 对序列后相同。不能只凭文件大小差异判定改过词表。

## 3. 百炼：上传什么、如何点击

官方“我的模型”文档当前列出北京地域支持 Qwen2.5-7B-Instruct 外部 LoRA；要求同一底模、rank 8/16/32/64 等条件及三个必要文件。导入仅在控制台操作。[官方导入说明](https://help.aliyun.com/zh/model-studio/my-model-center)

已准备四个独立目录：

```text
D:\AIlover\runtime\cloud\oss\hika\
D:\AIlover\runtime\cloud\oss\ayame\
D:\AIlover\runtime\cloud\oss\mugi\
D:\AIlover\runtime\cloud\oss\hotaru\
```

每个目录：`adapter_model.safetensors`、原样 `adapter_config.json`、从实际底模复制的 `config.json`、本地校验清单 `SHA256.json`。前三个文件合计 **323,015,715 字节/角色**；四份合计 **1,292,062,860 字节**。OSS 只需上传前三个，校验清单保留在本地或独立清单目录。导出采用硬链接避免本机重复占盘；这些文件视为只读，不能直接编辑导出文件，否则会影响同一硬链接对应的运行文件。

本地复核命令（仓库根目录 PowerShell）：

```powershell
.venv/Scripts/python.exe scripts/prepare_cloud_models.py
.venv/Scripts/python.exe scripts/verify_cloud_bundle.py
```

控制台步骤（本次没有替你执行，也没有批准产生费用）：

1. 进入百炼北京地域的“我的模型”，点击“导入模型”。选择 **Qwen2.5-7B-Instruct**，不能选 Qwen3 或其它 7B。
2. 按首次导入提示授权服务关联角色，为 OSS Bucket 添加 `bailian-datahub-access=read` 标签。使用符合平台要求的存储类型、加密方式和地域；不要选归档类或 SSE-KMS。私有 Bucket 可以使用。
3. 建立 `ailover/hika/` 等四个 OSS 子目录，将各自前三个文件直接放入；不要打 ZIP，不要选 Bucket 根目录，不要混合四个角色。
4. 表单选择“从 OSS 导入”，逐角色指定对应子目录，等待平台文件校验、导入状态。保留失败原因，不修改权重或 LoRA 参数绕过校验。
5. 特别检查原 `base_model_name_or_path` 是训练时的本地路径，且 revision 为 null：本地没有改写该字段。若平台因此拒绝，先获取官方允许的元数据修复方式；不能把未知 revision 填成猜测值。
6. 导入成功后进入模型部署界面，检查该账户/模型是否出现“按 Token”选项。出现并获计费批准后再部署；记录四个实际模型 ID 和所属业务空间。导入成功不代表已创建服务。
7. 若只开放按时部署，先看价格，不自动创建常驻服务。可转用下面的 vLLM Flex 方案。

按 Token 文档只保证部分 LoRA 高效 SFT 模型，不能从支持底模列表推导外部 Adapter 一定获得此资格。当前北京 Qwen2.5-7B-Instruct 表价为输入 ¥0.5/百万 Token、输出 ¥1/百万 Token；无推理用量不计推理费，但吞吐/并发由平台设定。四个模型按各自实际请求计量，OSS 请求、存储、流量另外计费。[官方 Token 部署与价格](https://help.aliyun.com/en/model-studio/model-deployment-token)

## 4. 文本备选：RunPod vLLM Multi-LoRA

四份 Adapter 的底模相同，因此准备一个 vLLM 引擎加载四个命名 Adapter，无需合并或修改权重。[vLLM 官方 LoRA serving](https://docs.vllm.ai/en/stable/features/lora/)

实现文件：`D:\AIlover\deploy\cloud\text\Dockerfile`、`launch.py`、`gateway.py`。镜像标签固定 `vllm/vllm-openai:v0.8.5`；`--max-lora-rank 32 --max-loras 4 --max-cpu-loras 4`，上下文 4096，显存比例 0.85。没有量化、合并 Adapter 或偷偷换底模。基础镜像 tag 仍可能被上游重发；生产发布时应记录构建镜像 digest，当前未构建，不能填写虚构 digest。

上传布局（仅在百炼不能满足时需要这份完整底模）：

```text
/runpod-volume/ailover-text/base/        <- runtime/shared/Qwen2.5-7B-Instruct/
/runpod-volume/ailover-text/lora/hika/   <- runtime/cloud/oss/hika/ 的两个 adapter 文件
/runpod-volume/ailover-text/lora/ayame/
/runpod-volume/ailover-text/lora/mugi/
/runpod-volume/ailover-text/lora/hotaru/
```

底模需 config、generation_config、tokenizer、vocab/merges、权重 index 和全部四个分片；不用上传原游戏、训练集、优化器或旧 checkpoint。底模按现有检查 JSON 逐文件比对。网络卷挂载根为 `/runpod-volume`。[官方网络卷](https://docs.runpod.io/storage/network-volumes)

此方案使用 **Load Balancing HTTP Endpoint**，不是语音的 `/run` 队列接口。网关端口由 `PORT` 指定，默认 8000；vLLM 仅监听内部 127.0.0.1:8001。`/ping` 检查 vLLM 是否真正 ready，模型未加载返回 503。[官方 HTTP Worker 部署](https://docs.runpod.io/serverless/load-balancing/build-a-worker)

鉴权有两层：RunPod 边缘要求 `Authorization: Bearer RUNPOD_API_KEY`；应用网关要求 `X-AILOVER-Key: RUNPOD_TEXT_SECRET`，该值与 Worker 环境的 `TEXT_GATEWAY_SECRET` 一致。内部 vLLM 使用独立 `VLLM_API_KEY`。不要把 vLLM 内部 Key 当成 RunPod 边缘 Key，否则网关会拒绝。

模型别名：`ailover-hika`、`ailover-ayame`、`ailover-mugi`、`ailover-hotaru`。服务器只接受这些别名；流式响应直接代理，并在断连时关闭上游。上传底模后可先评估一张 24GB GPU、最小 Worker=0、最大=1；实际可运行并发和显存必须实测，不能把估算当成功。未准备 Modal 第二套实现，因为 RunPod 已作为主要备选，避免重复维护。

## 5. GPT-SoVITS：一个 Worker 服务四位角色

源码与实际训练版本一致，固定提交 `b4570b876f5c086819ba84e3215472733c6a7b70`，版本 `v2Pro`。Dockerfile 固定 PyTorch 2.5.1/CUDA 12.4 镜像，约束 transformers 4.51.3、PEFT 0.15.2、numpy 1.26.4、pyopenjtalk 0.4.1、RunPod SDK 1.7.13 等。

`training-environment.lock.txt` 从真实训练包的 Linux freeze 提取可移植 `==` 版本；Conda 本地 file 引用没有冒充 PyPI 包，记录在 `nonportable-packages.json`。这不是已验证可构建的镜像锁：本机没有 Docker，尚未完成依赖解析、镜像构建及 CUDA 验收。构建若出现真实冲突，应保留上述模型/源码版本，定位具体依赖，不能宣称静态检查替代构建。

已生成最小部署目录：**`D:\AIlover\runtime\cloud\runpod-tts\`**。34 个数据/配置文件，**2,781,531,683 字节**，另附 `SHA256.json`。不是上传所有历史训练包。

包含每角色一份 S1（e15）、一份 S2（e12）和一段参考 WAV，以及真实日语参考文本；共用中文 RoBERTa、HuBERT、SV、G2PW 与离线日语/NLTK 词典。映射见 `manifest.json`，每个角色的 YAML 为 JSON 合法子集。共用预训练资源只保留一份，模型切换只更新同一个引擎的 S1/S2。

需要重建目录时：

```powershell
.venv/Scripts/python.exe scripts/export_serverless_assets.py
.venv/Scripts/python.exe scripts/verify_cloud_bundle.py
```

未来获批准后的部署步骤：

1. 在能运行 Docker 的 Linux amd64 构建环境，从 `deploy/cloud/tts` 构建并推送镜像；不要把权重或任何 Key COPY 进镜像。命令示例：`docker build --platform linux/amd64 -t YOUR_REGISTRY/ailover-tts:v1 deploy/cloud/tts`。注册表路径需要自行替换。
2. 创建合适地域的网络卷，用 RunPod S3 兼容上传工具把 `runpod-tts` **目录内容**上传到卷内 `ailover/`。最终为 `/runpod-volume/ailover/manifest.json`，不要多嵌套一层 `runpod-tts`。网络卷创建后即可能收费；本次没有创建。
3. RunPod Serverless → New Endpoint → Import from Docker Registry，选 **Queue-based**，镜像为构建后的真实 URL，挂载上述卷。环境设 `MODEL_ROOT=/runpod-volume/ailover`，Secret 设 `WORKER_SHARED_SECRET`。它须与 Django 的 `RUNPOD_WORKER_SECRET` 一致。
4. 初始最小 Worker=0、最大=1、并发处理=1、空闲回收约 5 秒；设置执行超时例如 180 秒、任务 TTL 例如 600 秒。具体字段/单位以当前控制台为准。不要创建四个常驻服务。GPU 首先选择有足够显存的类型；4GB 空闲检查仅是拒绝明显不足的保护，不保证实际模型能装下。
5. 服务创建和计费获批准后，再进行健康请求、逐角色中文合成、试听、超时/取消和连续切换验收。[官方部署说明](https://docs.runpod.io/serverless/workers/deploy)

Worker 启动先核对全部 SHA256，准备只读模型软链接、解压词典到容器 `/tmp`。上游加载权重时会改写配置，因此运行配置特意改到 `/tmp/ailover-current-tts.yaml`，不会改写挂载卷上的已校验配置。单一互斥锁覆盖模型切换和推理；切换失败会清空引擎和角色状态，下一次重新加载，避免部分切换导致串音色。异常或显存错误释放引擎并清理 CUDA 缓存；不会无休止重试推理。

每个任务包含签名、时间戳、角色和 request_id；签名覆盖文本，过期或被改角色会拒绝。相同 request_id 和完全相同载荷可复用本 Worker 的短期完成缓存（600 秒，最多 16 项/32MiB）；相同 ID 不同载荷拒绝。缓存不是跨实例、跨重启的持久幂等保证，因此客户端**不重试提交 POST**。

音频在内存中合成并转真实 MP3，以 base64 返回，不写公共 URL、不落临时音频；仅词典缓存留在容器临时目录。文本最多 300 字，输出最多 120 秒。平台队列负责排队，Worker 内锁负责串行；吞吐不足时需要实测后再增加 Worker。

请求为异步 `/run`，Django 轮询 `/status/{id}`，失败、超时或用户中断则尽力 `/cancel/{id}`。对状态 GET 的临时网络错误、429/5xx最多重试三次，提交 POST 不重发。平台取消不能保证立刻中止正在进行的 CUDA kernel；执行超时和 Worker 生命周期仍是最终约束。[官方队列 API](https://docs.runpod.io/serverless/endpoints/send-requests)

参考音频说日语，`prompt_lang=ja`、参考文本为日语；生成目标 `text_lang=zh`。没有中文真实录音，也没有伪造中文监督标签。本次沿用现有已对齐参考样本，不宣称其为试听筛选后的最优样本。中文自然度、相似度、数字与多音字需真实 GPU 合成和人工试听。

冷启动包括校验、词典准备和模型加载，首次音频可能明显等待；未实测加载秒数，不提供虚构延迟。此 Worker 返回每句完成后的 MP3，**不提供模型内部 token 级流式音频**；保留前端原有按序句子播放、语音开关和中断。SSE 文本仍实时流出。

## 6. AIlover 接入与安全配置

新增后端适配器为 `backend/web/cloud_models.py`；原本地 GPT-SoVITS 和 OpenAI 兼容 Provider 保留。角色路由由管理员 JSON 决定，用户消息不能指定任意模型或 URL。

- 百炼模板：`D:\AIlover\deploy\cloud\manifest.example.json`。DashScope 原生增量 SSE，业务空间对应的 `DASHSCOPE_API_KEY` 仅留在后端环境。
- RunPod 文本模板：`D:\AIlover\deploy\cloud\manifest.runpod.example.json`。OpenAI 兼容地址为 `https://TEXT_ENDPOINT_ID.api.runpod.ai/v1`，与队列地址不能混用。
- 可以逐角色选择不同文本 Provider；四角色语音使用同一个真实 `runpod_endpoint_id`，角色参数决定加载哪份权重。

把所选模板复制到被忽略的 `runtime/cloud/manifest.live.json`，填写真实模型 ID、Endpoint ID，然后在后端本地 `.env` 设置：

```dotenv
CHARACTER_MODELS_ENABLED=true
CHARACTER_MODELS_MANIFEST=D:/AIlover/runtime/cloud/manifest.live.json
DASHSCOPE_API_KEY=<业务空间对应Key，仅百炼使用>
RUNPOD_API_KEY=<限制到所需端点的Key>
RUNPOD_WORKER_SECRET=<与语音Worker共享密钥相同>
RUNPOD_TEXT_SECRET=<与TEXT_GATEWAY_SECRET相同，仅文本备选使用>
TTS_TIMEOUT_SECONDS=300
RUNPOD_TTS_TIMEOUT=240
GENERATION_TIMEOUT_SECONDS=360
```

以上是占位符示例，不能直接启用。`.env.example` 没有任何真实 Key。不要放到 Vue、VITE 变量、Git、请求日志。服务端未配置必要 Key 会明确失败，而不是使用另一个角色来凑结果。

文字模型请求不自动重发，避免重复计费和重复 SSE；语音失败保留文字回复及已有不可用提示，不悄悄换成另一角色音色。保留 LangGraph、Story-Aware RAG、Context Builder、结构化记忆、关系状态、历史、SSE、OrderedAudioPlayer。没有修改数据库或训练数据。

## 7. 验证记录与下一步验收

本地实际完成：

- 四个 Adapter 的 SafeTensors 结构、维度、配置和 tokenizer 语义一致性检查。
- 四个 OSS 目录全部三个必要文件逐个 SHA256 复核；语音部署目录 34 文件 SHA256 复核。
- 两个 Dockerfile 的 COPY 源、固定版本标签、Python 语法与四角色挂载映射静态检查。
- 最终 Django 全套 **140 项回归通过**；包含云端相关 12 项测试及已有聊天、记忆、语音和数据保护测试。
- 前端 22 项 Node 测试通过，Vue 类型检查、Vite 生产构建通过。
- 原生 DashScope SSE 与异步 ainvoke Mock；RunPod 成功、失败、超时、用户取消、返回角色不符测试。
- Worker HMAC、篡改、过期、角色非法、重复 ID 命中与碰撞隔离测试。
- 模拟部分权重切换后显存错误，确认引擎及角色清空、重建后才能返回目标角色声音，挂载卷配置保持不变；未将此 Mock 当作真实 GPU 通过。
- vLLM 网关 3 项 CPU Mock：双层应用鉴权入口、四角色流式转发与内部 Key、未就绪返回 503。

本地日志：`runtime/cloud-full-backend-tests.log`、`runtime/cloud-provider-tests.log`。测试 Key 全为 fixture，不是真实平台 Key。验证脚本结果明确标记 `image_built=false`、`gpu_inference_tested=false`。

**未验证**：真实百炼导入/部署资格、平台请求、Docker 构建及依赖可解、GPU 显存与并发、启动耗时、语音质量、跨语言音色、真实平台取消行为和最终账单。不要把本地 Mock 视为这些项通过。

CPU 网关测试依赖可在隔离测试环境安装 FastAPI 0.115.12、Starlette 0.46.2 后运行：`python -m unittest discover -s deploy/cloud/text -p test_gateway.py`。正式镜像由固定 vLLM 镜像提供这些运行依赖，构建时仍须验证。

真实平台 Key、端点和计费批准齐备后，先用 `deploy/cloud/test_request.py --approved-billing --health` 检查语音 Worker；再加 `--role hika --output runtime/cloud/hika.mp3` 等逐角色验证。**健康请求也会唤醒 Worker 并可能收费**，本次没有运行此脚本。文本验收依次检查四个 model alias、SSE 首字、角色人格、多轮记忆、取消及并发；语音验收逐项试听中文数字、多音字、长句与快速角色切换。

## 8. 计费、停用和回滚

RunPod Flex 按 Worker 从启动到完全退出的秒数计费，向上取整；模型加载、执行及空闲等待会计费。镜像拉取、平台 cached models 下载通常在缩容状态进行，不应一概当作计费加载。Active 是常驻模式，当前方案不选它。[官方 Serverless 价格](https://docs.runpod.io/serverless/pricing)

当前官方存储表：容器盘约 $0.10/GB/月；网络卷小于 1TB 为 $0.07/GB/月，大于 1TB 档 $0.05/GB/月。GPU 秒价按实际型号和控制台选择，未创建资源，故没有“本项目实际每小时费用”。存储按配置容量/规则收费，不能用 2.78GB 文件大小替代实际购买卷容量；计算缩到零也不等于存储免费。注册表、OSS 及跨地域流量费用需按所用服务另计。

推荐先尝试百炼文本候选导入；确认支持按 Token 才采用该模式。语音用 Flex 单 Worker。若百炼不合适，文本另用一个 vLLM Flex Worker，与语音分开处理环境与排队；这不等于为四个角色租四张常驻 GPU。

回滚应用：将 `CHARACTER_MODELS_ENABLED=false` 后重启后端，恢复原有通用模型和语音配置；或把清单路径切回 `runtime/manifest.json`（本地 GPU 服务必须已可用）。不要删除新权重、训练包、用户数据或数据库。

停用收费服务：先禁止应用新请求并取消队列中的任务，再将 RunPod 端点暂停/禁用或按平台方式停用全部 Worker，核对没有 Active Worker；百炼在模型部署页下线服务，不能只关闭网页。网络卷、OSS、容器注册表仍可能保留存储费；导出备份后是否删除存储须另外决定，本次不删除。吊销不用的 Key，确认停用账单状态。需要恢复时重新部署同一权重并复核清单哈希。

当前仍缺：阿里云账号/业务空间与导入校验、实际四个模型 ID、部署模式资格；RunPod 账户/端点/网络卷/镜像 URL/Key/共享密钥；可构建 Docker 的环境；以及用户对资源配置和计费的明确批准。拿到这些之前不能称为“线上八份模型已可用”。
