# 水无月萤：原作提取与训练材料方法

本轮在既有 AIlover 通用角色、LangGraph、记忆、检索和静态舞台中新增《天津罪 / アマツツミ》的水无月萤，slug 为 `hotaru`。原始游戏和旧三位角色训练包只读，材料仅留本机。数据准备不等于模型已经微调或声音效果验收。

## 方法来源

- [Purple software 原作官网](https://www.purplesoftware.jp/products/amatsutsumi/index.html)：确认作品与人物信息的主来源；具体台词和素材以本机实际游戏文件为准。
- [GARbro](https://github.com/morkt/GARbro)、[CPZ实现](https://github.com/morkt/GARbro/blob/master/ArcFormats/Purple/ArcCPZ.cs)：CMVS CPZ6封包与原资源读取。提取工具固定发行版、留下载URL和SHA256，不执行游戏程序。
- [ChatHaruhi](https://github.com/LC1332/Chat-Haruhi-Suzumiya)、[RoleLLM](https://github.com/InteractiveNLP-Team/RoleLLM-public)、[Character-LLM](https://aclanthology.org/2023.emnlp-main.814/)、[CoSER](https://github.com/Neph0s/CoSER)：角色资料与原作风格示例分开，保留说话人和前序情境，区分原作与另写互动，不凭空补内心或路线事实。
- [LLaMA-Factory数据格式](https://llamafactory.readthedocs.io/en/latest/getting_started/data_preparation.html)：ShareGPT的system与human/gpt角色字段，独立注册train/validation/test。
- [GPT-SoVITS格式](https://github.com/RVC-Boss/GPT-SoVITS#dataset-format)、[音频预处理](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py)：日语音频搭配`ja`及真实日文转写，中文译文另存。模型版本与适配限制另见[此前研究](TTS_PREPARATION_RESEARCH.md)。

## 与旧角色相同的交付层

1. 真实游戏立绘、头像、背景及选择依据，前端沿用同样的静态舞台和聊天工作区。
2. 角色卡、开场白、快捷话题、独立音色环境变量、旧风格检索与Story检索。复用现有Agent流程，不为萤复制一套不一致的记忆逻辑。
3. 中文文本V3：来源完整的原作上下文、原作续写与有结构依据的玩家互动；合成候选另存，不冒充原句，不自动进入正式训练。
4. 日语原声音频准备V1：完整合格集合、分组分区、少样本子集、参考候选、JA/ZH对齐、中文目标文字、排除与人工听审表。
5. 每包SHA256清单、独立来源复核、实际ZIP解压验证和可复现脚本。

萤此前没有V2文本包，因此如实记录没有同角色旧基线，不拿绯华、菖蒲或麦的语料伪造萤的历史数据。

## 跨引擎的来源差异

旧游戏是XP3/KAG，新游戏是CPZ6/PS3与汉化PKP。新记录使用实际二进制偏移、指令或字符串序号，不伪造`.ks`路径和物理行号。中日对齐依赖同源指令结构、说话人和voice ID，不能仅按语义或文本长度猜配。

原始资源和汉化补丁均只读，提取到`extracted/amatsutsumi`；角色与运行时来源另存`extracted/characters/hotaru`。未知说话人、冲突日文转写、缺译、路线/跳转无法确认、非语言发声和不合格声音均保留记录和原因。

## 数据策略

中文SFT保留目标发言前2–6条同文件、同场景的真实前序信息。输入不包含目标回复或未来台词；无法判断的情境隔离。原作主角为织部诚，当前real_user不自动等同于诚。原作背景和现实用户记忆分开，不继承旧角色的称呼和人物身份。

分区以整个来源文件为单位，同一剧情来源不跨train/validation/test。去除相同/高相似目标回复，不靠重复窗口虚增数量。合成候选带明确来源、内容哈希和待审核状态，没有真人审核则mixed与canonical一致。

音频保持游戏逐句原边界，转换副本为32kHz、单声道、16-bit PCM，不覆盖原声。不自动修剪、拼接、降噪。1–20秒、能量及饱和比例是当前本地技术策略，不是GPT-SoVITS所有版本的统一约束。全量不缩成十五分钟；另留train中的最多十五分钟子集。

参考候选由新素材重新选择，保留日文台词和来源，单独预留，不进入训练/验证/测试标签。数值合格并不能证明没有背景音乐、多人重叠、实际截断或字幕朗读差异；这些状态保持未测、待真人听审。

真实中文录音和有效中文监督配对为零。当前材料支持日语角色适配准备，以及未来多语种底模用日语参考与中文目标进行跨语言任务。真正中文语音监督训练仍需目标音色的真实中文录音与准确中文转写；不把日语重标为中文，不把生成语音冒充原配录音。

## 本地入口

- `scripts/amatsutsumi_extract.py`：CMVS原始来源提取和结构复核。
- `scripts/prepare_hotaru_assets.py`：原游戏图像解码与舞台资产。
- `scripts/build_hotaru_training.py`：中文文本与日语音频准备、打包、实际解压。
- `scripts/hotaru_training_common.py`：标准库包校验和文本来源规则。
- `scripts/install_hotaru_runtime.py`：保留旧数据的检索/本地数据库安装。

随包`tools/verify.py verify --root /解压后的包`验证所有来源和数据；语音包支持`paths`，在包外生成训练机器本地绝对路径`.list`。不修改受清单管理的交付文件。
