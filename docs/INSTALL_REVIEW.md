# 源码验收包安装与复现

本包包含应用和工具源码、迁移、前端锁文件、测试、合成fixture及脱敏评测报告。不是EXE、离线依赖安装器或模型权重包。安装依赖需要网络。源码解压到新目录后运行，不覆盖现有AIlover用户库。

不含真实`.env`、用户库/媒体、游戏剧本/台词/音频、本地索引、node_modules或.venv。原作素材在作者机器保留；下载此包的人可离线运行合成测试，不能直接重现3272条原作索引的benchmark。

## Windows安装

验证环境：Python3.12.14、Node24.14.0。建议Python3.12；Node要求以frontend/package.json engines为准（20.19+或22.12+，本轮使用24）。在解压后的AIlover-review目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock-windows.txt
npm --prefix frontend ci
.\.venv\Scripts\python.exe backend/manage.py check
.\.venv\Scripts\python.exe backend/manage.py test web --noinput
npm --prefix frontend test
npm --prefix frontend run build
.\.venv\Scripts\python.exe scripts/sync_template.py
.\.venv\Scripts\python.exe backend/manage.py evaluate_system --output-dir backend/evaluations/review-offline
```

requirements-lock-windows.txt记录作者已验证环境的95个分发包，包括开发/打包依赖；它不是跨平台锁。一般依赖边界另见backend/requirements.txt。没有在新机器上重新联网下载95个依赖；源码包解压后的回归使用作者现有环境执行，不能把它描述为全新系统安装验收。

测试与评测不用模型密钥，不需GPU，不会创建真实模型回复。没有原作数据时检索会为空。`evaluate_system`不加story-data-dir即可运行全合成契约；输出路径不能重复。

实际源码包解压后的完整后端101项通过（26.253秒），旧检索测试已使用合成fixture，不依赖原作语料目录。最终筛选隐私2项通过。执行边界记录在evaluation/review-package-validation.json；前端5项/类型检查/构建沿用此前真实运行结果，没有在解压目录重新下载npm依赖。

ZIP可用 `python scripts/verify_review_package.py 你的源码包.zip` 只读验证清单/哈希/源码语法；随包外置.zip.sha256可用于确认下载完整性。

## 运行应用

```powershell
# 新解压目录首次运行创建新库；已有用户库应先backup_data再migrate。
.\.venv\Scripts\python.exe backend/manage.py migrate
.\.venv\Scripts\python.exe launcher.py --doctor
.\.venv\Scripts\python.exe launcher.py
```

可以注册新测试账号、创建自定义角色；`seed_ousama --username 你的新测试账号`可安装角色卡并生成占位图片，本包没有原作图片/音频。无Key时真实聊天会给配置错误，不代表流式功能失败。原作卡也不等于已经审核的Lore。

需要真实文字聊天时，在自己电脑用配置模板创建`.env`，设置API_KEY/API_BASE/MODEL，先关闭TTS。密钥不上传到GPT；模型必须支持项目使用的OpenAI兼容调用。TTS/ASR沿用云端WebSocket协议，需要可用服务密钥、模型和音色；任意本地语音权重不能直接替换协议。

前端开发需另开终端 `npm --prefix frontend run dev`；后端 `manage.py runserver`。生产launcher使用构建后静态资源。VAD资源由npm prebuild/predev从依赖准备。

## 原作与桌面验收范围

如果持有合法本地剧本，可用build_story_data.py构建到新的目录，指定STORY_DATA_DIR，再审核facts/gold。本包不含这些素材，不能用合成gold代表原作剧情效果。

本包保留ailover.spec供审阅，但旧spec含私有seed_assets数据入口；本包刻意未包含该目录，不能照抄旧README的PyInstaller步骤就宣称新EXE可用。桌面打包仍需在本机准备授权资产/调整打包入口并单独验收。源码包不自动复制或发布这些素材。

完整能力边界、回退及迁移见PHASE4_DELIVERY.md；网页版GPT可审代码，但没有执行工具时应把代码检查和实际运行明确区分。
