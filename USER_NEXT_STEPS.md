# 需要人工完成的最终验收

2026-10-14：源码已实现Phase1–4工程链路，默认backend/story_data已构建，用户库已备份迁移。优先用 `launcher.py --doctor` 和 `launcher.py` 运行源码；旧EXE不会自动包含新代码。

剩余条件：本机配置模型密钥；审核原作facts/gold；显式执行真实模型/Embedding及人工盲评；验收云语音、麦克风和重建EXE。无需提供密钥或上传素材，无需训练。见 [最终交付](docs/PHASE4_DELIVERY.md)、[评测](docs/EVALUATION.md)。

以下仅为旧桌面包历史说明。

## 1. 先让文字聊天运行（必须）

新版程序：`D:\AIlover\dist\updated\AIlover\AIlover.exe`。

新版已复制当前开发数据库中的账号、两位角色和媒体素材，可以沿用原账号登录。
请保留整个AIlover目录，其中的 `_internal` 和 `data` 都是运行所需的文件。

在它旁边的 `data` 目录，将 `.env.example` 复制为 `.env`，用文本编辑器填写：

```dotenv
API_KEY=你的模型服务密钥
API_BASE=该服务的OpenAI兼容接口地址
MODEL=该服务实际允许使用的模型名称
TTS_ENABLED=false
```

模型名称、接口地址和密钥要来自同一个可用服务。密钥留在本机配置文件，不必发到聊天里。
修改后重新启动程序，登录现有账号，在「运行设置」查看配置状态，再向角色发一条文字消息。
遇到错误时，把界面的错误提示告诉我，不要附带密钥。

源码模式使用仓库根目录 `D:\AIlover\.env`，启动命令为：

```powershell
.venv/Scripts/python.exe launcher.py
```

## 2. 确认你想要的声音（文字聊天正常后）

目前没有可验证的原角色克隆音色，也没有运行中的本地语音模型，因此本轮没有代替你开通服务、上传素材、训练模型或调用付费语音。

- 如果使用云声音复刻：你需要取得可用的音色ID，并确认该音色对应的模型。随后在角色编辑页填写音色ID，在.env填写对应的TTS_MODEL和语音密钥，设TTS_ENABLED=true。
- 如果聊天模型来自其他平台，可用TTS_API_KEY单独填写百炼语音密钥。
- 如果使用本地语音模型：先确认愿意采用这个方案，以及可用的显卡、模型文件和服务地址，再让我完成接入；当前代码尚未接入本地语音模型。

现成参考语音位于 `backend/seed_assets/hika/voice_ref.opus` 和 `backend/seed_assets/ayame/voice_ref.opus`，文字在同目录的voice_ref.txt。
只有试听才能判断音色是否像原角色，我无法代替你做这个主观确认。

## 3. 确认角色还原与素材（可随后做）

- 连续和两位角色聊几轮，把不像本人、反复口癖、记错称呼、乱编经历的例子告诉我。
- 原作设定和译名需要熟悉游戏的人审校；本轮保留现有角色卡，没有擅自新增未经核实的人物经历。
- 选定你要使用的头像、立绘和背景，或明确指定原作中的素材。现有占位图保留；解码和接入仍可由我继续做。
- 在另一台没有开发环境的Windows电脑运行新版，确认窗口和音频播放是否正常。当前机器上的验证不能代替这一步。

## 已由我准备好的工具

不需要模型密钥的操作：

```powershell
.venv/Scripts/python.exe backend/manage.py doctor
.venv/Scripts/python.exe backend/manage.py backup_data
.venv/Scripts/python.exe backend/manage.py audit_corpus
.venv/Scripts/python.exe backend/manage.py evaluate_roleplay
```

最后一条只验证12个评估用例，不调用模型。配置好密钥后，如果你想批量生成待审阅的回复，可以显式运行：

```powershell
.venv/Scripts/python.exe backend/manage.py evaluate_roleplay --run --slug hika
```

`--run`会使用模型服务额度，不调用语音、不写入你的聊天或记忆，报告需要人工审阅。
备份包含账号、记录、记忆和媒体，请妥善保存；恢复前关闭程序，先保存当前数据再替换。
