# AIlover 2.0 重构交付报告

更新：2026-10-20。基于当前真实仓库，在已有 `ailover-2.0-redesign` 分支继续实施，随后按用户要求整理到独立 GitHub 分支；游戏素材保留在本地。保留并衔接了开始时已有的 Phase 1 页面、未提交的好友接口、素材映射和状态类型。

## 已实际实现

### 角色与视觉

- 仅使用用户指定的本游戏角色、美术和场景。原创示例角色的代码、图片、映射与截图已撤下，真实数据库没有新增原创角色。
- 首页保留并完善现有设计系统、角色精选、搜索、最近聊天与角色卡；补齐作者入口、触屏可见操作、错误反馈和安全的异步请求收尾。
- 修复 Tailwind 语义色 `--color-base` 生成 `text-base` 颜色类，与字号类冲突而导致文字变暗的问题；将注册色名改为 canvas，保留 CSS 变量。深浅主题均实测。
- 角色卡的多个根节点曾破坏首页双列网格，现已用单一容器组织封面、作者和错误信息。
- 角色资源不写入模型字段或覆盖用户上传。展示接口按本地映射选择游戏头像、背景和立绘；素材缺失回退到原字段。

### 游戏素材修复

游戏角色表确认：**绯华为 2 号，菖蒲为 8 号**。先前 st1/st2 的映射并不对应这两人。

现有 TLG 解码器的色彩变换第 8、12 项错误叠加蓝通道，已修复。之前缺脸、面部跑到腿部的图不是可直接使用的完整立绘；需要按游戏脚本的原始画布坐标叠加人物底图、表情、配件。

新增 `scripts/prepare_game_stage.py`，可复现地从本地游戏生成：

| 角色 | 立绘 | 头像 | 背景 |
|---|---|---|---|
| 绯华 | 467×1600，约 104 KiB，透明 WebP | 384px 内，约 37 KiB | 游戏 bg1_0，约 132 KiB |
| 菖蒲 | 493×1600，约 120 KiB，透明 WebP | 384px 内，约 42 KiB | 游戏 bg4_0，约 201 KiB |

输出位于被 Git 忽略的 `backend/media/character/stage/`，包含本地来源哈希记录。脚本不写数据库，不改 `finetune_data/` 或原训练/翻译脚本。没有将游戏原始图片或音频提交到源码。

### 完整聊天工作区

新增可直接访问的 `/chat/:friendId`。旧首页、好友、个人空间与角色入口全部转向同一工作区，旧 ChatField.showModal 调用保留为路由兼容入口。

桌面为轻量导航、主角色舞台、右侧对话栏。手机为上方舞台、下方历史与输入；沉浸模式为大舞台和底部名称字幕。普通与沉浸模式保留同一份消息数组、InputField 和 OrderedAudioPlayer，不因模式切换重建 SSE。

保留流式文本、开场白、快捷话题、停止、失败重试、语音开关、按需麦克风、记忆与记录管理、搜索、清空、导出及开发调试组件。消息使用 Vue 文本插值，长文本换行，不执行模型 HTML。

历史列表加载旧消息保持高度差；阅读历史时不随每个 token 强制滚动，提供“回到最新消息”。隐藏的沉浸历史不会重置滚动位置。原生 dialog 用于记忆管理，包含浏览器焦点约束和 Escape 行为。

修复懒加载初始路由与登录信息请求的竞态：等待 router.isReady 后挂载，未登录直接访问聊天会跳转登录，并在登录后返回原会话。移动端隐藏工作区背后的全站导航，避免重复焦点入口。

路由按页拆包；VAD/麦克风模块异步加载，播放器仅在用户需要语音时初始化。舞台静态渲染不依赖 WebGL；尊重减少动画设置，监听并清理 visualViewport/window resize，底部输入适配 safe area。

### 真实状态与语音生命周期

InputField 继续使用原有 SSE、processId/generation_id 校验、取消清理轮询和 OrderedAudioPlayer。舞台由实际事件显示 idle、listening、thinking、speaking、interrupted、error。

speaking 由 HTMLAudioElement 实际 playing 事件驱动；waiting、ended、stop 与失败会更新状态、清理旧代际回调。没有根据用户关键词猜表情，也没有把静态图片移动称为 Live2D。没有任何音频片段的纯文字/降级回复会静默释放播放器，避免空媒体被误报为解码失败。

### 后端基础

- 衔接带所有者检查的 `GET /api/friend/get_single/?friend_id=`，用于刷新后恢复工作区。
- 首页与好友接口复用统一角色展示 payload；新增短 description，避免把整段角色提示词当作卡片简介；quick_replies 校验为有限长度的字符串列表。
- 本地素材映射检查 display_ready、文件存在、路径遍历、Windows 反斜线和解析后目录边界。只读取允许的展示目录。
- SSE 保留原 start/content/audio_seq/generation_id/warning/error/[DONE]，start 增加向后兼容的 audio_enabled 字段；取消接口与模型、RAG、记忆管线保持原语义。
- ASGI 使用逐项异步桥接同步生成器，避免整段缓冲；桌面 WSGI 保留。
- 新增 `backend.production`、生产依赖清单、健康检查、PostgreSQL 环境配置、基础限流、HTTPS/代理设置、静态目录配置与 Nginx 示例。

## 新旧组件关系

| 旧入口 / 组件 | 现在的职责 |
|---|---|
| Character / 首页 HeroCharacterCard / CharacterCard | 复用角色卡，get_or_create 后导航聊天；编辑、删除及作者入口保留 |
| ChatField.showModal | 兼容旧调用，转向独立聊天路由 |
| ChatWorkspace（新增） | 好友加载、消息状态、模式与记忆弹窗 |
| CharacterStage（新增） | 游戏背景、透明立绘或头像回退、状态提示 |
| ChatHistory / Message | 共享历史、分页位置、阅读跟随与安全文本展示 |
| InputField / OrderedAudioPlayer | 复用真实 SSE、TTS、取消及输入逻辑，增加真实播放状态通知 |
| Microphone | 懒加载 VAD、原 ASR 接口和语音打断，卸载销毁录音资源 |
| ConversationManager | 继续承载记忆、历史搜索、导出和清空，由工作区 dialog 展示 |

## 已测试验证

| 验证 | 实际结果与边界 |
|---|---|
| `npm run build` | Vite 构建、vue-tsc 类型检查、Django 模板哈希同步通过 |
| `npm test` | 20 项通过：状态、请求竞态、音频乱序、代际隔离、停止、无音频、播放事件清理和渲染回退 |
| Django check | 无问题 |
| Django test `web.test_redesign web.tests web.test_voice_pipeline web.test_delivery_safety` | 61 项通过：所有者隔离、接口、ASGI 桥接、生成/取消、语音故障降级等；没有声称跑过整个测试库 |
| `scripts/test_game_stage.py` | 2 项通过：16 个色彩数学向量、原坐标面部/配件叠加 |
| TLG 真实图像核对 | 四个游戏图像与官方原生 C 解码结果逐字节一致；应用运行不依赖该诊断 DLL |
| `check --deploy` | 使用临时安全环境值测试生产配置，无问题；没有向公网部署 |
| 浏览器 | 实际运行 Vite+Django，并验证 Django 直接提供构建后的页面和静态资源 |

浏览器已实际操作：登录、进入游戏角色聊天、发送、分段 SSE、生成时切换沉浸、停止后新一轮、历史读取与刷新、记忆面板和新增人工记忆、深浅主题。无 API Key 的错误与重试入口在最终隔离无密钥服务验证；直接访问聊天的登录重定向、登录后返回原会话及切换到菖蒲也已在最终构建验证。

**SSE 成功路径使用明确标记的本地确定性测试模型，只用于交互验收，不代表真实 LLM 或 TTS 效果。** 浏览器验收账号、消息和人工记忆均写入 SQLite 临时副本，真实用户记录未被测试消息污染。

目标尺寸 1440×900、1920×1080、768px 平板、390×844、360×800 均检查。最终布局测量见 `docs/evaluation/redesign-layout.json`：文档宽度没有超出视口，输入框 bottom 在视口内，背景和立绘均加载成功。没有编造帧率、内存分数或旧设备性能保证。

截图位于 `docs/screenshots/`：home-desktop、chat-desktop-1440、chat-immersive-1440、chat-1920、chat-768、chat-390、chat-360、chat-immersive-mobile、chat-light。这些截图含本地游戏素材，默认不纳入 Git。

## 已提供扩展接口

`stage/renderer.ts` 定义角色资源契约、Renderer Adapter 的 mount/setState/dispose 生命周期与静态/Live2D 能力选择。实际实现的 renderer 是静态组件，缺少模型、授权标记、运行时或 WebGL 时选择静态。

**未实现 Live2D 展示或真实口型同步**；没有 `.model3.json`、`.moc3`、动作或表情参数资源，也未安装 Cubism Core。不要将本轮静态呈现当作 Live2D 体验。

## 仍需外部条件 / 后续完成

- 真实 LLM、TTS 与 ASR 服务的凭证、音色和网络验收；实际音频播放、麦克风硬件权限、浏览器阻止播放、弱网中断和多设备声音测试仍需逐项完成。
- iOS/Android 真机虚拟键盘、极长历史压力测试与低配置设备实测；本轮为浏览器视口测试。
- 若要动态表情，需审核并映射更多游戏表情，再通过独立结构化字段驱动；当前每个角色采用一套完整静态表情，不伪造模型情绪控制。
- 游戏素材的公开分发许可尚未获得或证明，仅按用户要求本地使用。公开作品集/网站需另行确认素材权利；本轮没有上传游戏资源或公开网站。
- API 保留旧 result 字段及响应语义；统一错误码目前覆盖新增分页错误等必要接口，尚未进行全站错误响应重写。
- PostgreSQL 实例、证书、服务器及真实 ASGI 部署验收尚未进行；uvicorn 未安装。生产配置和单测通过不等于云端已经上线。
- generation registry 与取消状态仍在进程内，当前生产方案限定一个 worker；多实例需要共享任务注册表、锁、缓存及更严格的资源预算。默认 DRF 限流不是计费日配额。
- 桌面打包入口和 spec 保留，未重新构建或运行新 EXE。

## 运行方法

已有账号与真实服务：

```powershell
cd D:\AIlover\frontend
npm run build
cd D:\AIlover
.venv/Scripts/python.exe scripts/prepare_game_stage.py
.venv/Scripts/python.exe backend/manage.py runserver 127.0.0.1:8000
```

访问 `http://127.0.0.1:8000/`，使用现有账号。模型服务仍读取现有 `.env`。素材脚本已在本机实际运行，正常只需首次准备或重建资源时执行。

隔离验收：`.venv/Scripts/python.exe scripts/preview_redesign.py --fixture-stream`，访问 8001，账号 `redesign-preview / preview-only-2026`。该模式不调用外部模型，不能用它评价真实角色回答质量。

详见 `docs/DEPLOYMENT_2.0.md`；参考项目代码、版本与 License 核对详见 `docs/REFERENCE_RESEARCH.md`。

## 文件清单

下列包含本轮修改及衔接的起始未提交文件；没有执行 git reset、清空数据库或重建训练数据。游戏图与临时截图按忽略规则留在本机。

- `.gitignore`
- `backend/backend/production.py`
- `backend/backend/settings.py`
- `backend/backend/urls.py`
- `backend/requirements-production.txt`
- `backend/seed_assets/portrait_map.json`
- `backend/web/streaming.py`
- `backend/web/templates/index.html`
- `backend/web/test_redesign.py`
- `backend/web/tests.py`
- `backend/web/urls.py`
- `backend/web/views/friend/assets.py`
- `backend/web/views/friend/get_list.py`
- `backend/web/views/friend/get_or_create.py`
- `backend/web/views/friend/get_single.py`
- `backend/web/views/friend/message/chat/chat.py`
- `backend/web/views/health.py`
- `backend/web/views/homepage/index.py`
- `docs/AIlover_2.0_REDESIGN_REPORT.md`
- `docs/DEPLOYMENT_2.0.md`
- `docs/REFERENCE_RESEARCH.md`
- `docs/UI_REDESIGN.md`
- `docs/evaluation/redesign-layout.json`
- `frontend/index.html`
- `frontend/scripts/sync-template.mjs`
- `frontend/src/App.vue`
- `frontend/src/assets/main.css`
- `frontend/src/components/character/Character.vue`
- `frontend/src/components/character/chat_field/ChatField.vue`
- `frontend/src/components/character/chat_field/chat_history/ChatHistory.vue`
- `frontend/src/components/character/chat_field/chat_history/message/Message.vue`
- `frontend/src/components/character/chat_field/input_field/InputField.vue`
- `frontend/src/components/character/chat_field/input_field/Microphone.vue`
- `frontend/src/components/home/CharacterCard.vue`
- `frontend/src/components/home/HeroCharacterCard.vue`
- `frontend/src/components/home/RecentChats.vue`
- `frontend/src/components/home/useOpenChat.js`
- `frontend/src/components/shell/AppShell.vue`
- `frontend/src/js/utils/orderedAudio.js`
- `frontend/src/main.js`
- `frontend/src/router/index.js`
- `frontend/src/stage/CharacterStage.vue`
- `frontend/src/stage/characterState.ts`
- `frontend/src/stage/renderer.ts`
- `frontend/src/types/shims.d.ts`
- `frontend/src/views/friend/ChatWorkspace.vue`
- `frontend/src/views/friend/FriendIndex.vue`
- `frontend/src/views/homepage/HomePageIndex.vue`
- `frontend/src/views/user/account/LoginIndex.vue`
- `frontend/tests/characterState.test.mjs`
- `frontend/tests/orderedAudio.test.mjs`
- `frontend/tests/renderer.test.mjs`
- `frontend/vite.config.ts`
- `scripts/deploy/nginx.conf`
- `scripts/prepare_game_stage.py`
- `scripts/preview_redesign.py`
- `scripts/test_game_stage.py`
- `scripts/tlg.py`
