# AIlover 2.0 UI 重设计规范（Phase 0 审计结论 + 设计契约）

> 分支：`ailover-2.0-redesign`。本文档是 Phase 1–3 施工的统一依据。
> 审计日期：2026-10-19，基于真实仓库（详见各节文件路径）。

## 1. 定位

Premium Anime Companion / Interactive Visual Novel Experience。角色是视觉与交互中心。
设计语言：Midnight Lavender / Soft Rose / Warm Ivory——深紫底、暖白字、低饱和粉点缀。

## 2. 现状关键事实（施工约束）

- 聊天当前是 `Character.vue` 里 `ChatField.showModal()` 的 DaisyUI `<dialog>`，**无独立路由**；
  `history` 等状态在组件内存，关模态即丢 → 新增 `/chat/:friendId` 工作区路由，旧路由全部保留。
- SSE 契约（`backend/web/views/friend/message/chat/chat.py`）：POST `/api/friend/message/chat/`，
  body `{friend_id, message, audio, generation_id}`；事件帧：`start` / `{content}` / `{audio, audio_seq}` /
  `{warning}` / `{error}` / `[DONE]` / `: heartbeat`；取消：POST `…/chat/cancel/` `{friend_id, generation_id}`。
  **这套契约与 `orderedAudio.js`（代际绑定）、InputField 的 processId 双层校验互相咬合，必须整体搬移，不得拆散。**
- 后端无「按 friend_id 取单个好友」端点 → 需新增 `GET /api/friend/get_single/?friend_id=`（带权限校验）。
- 角色资产：`Character.photo`（512×512 无透明）、`background_image`（1280×720）；
  透明全身立绘仅存在于 `extracted/sprites/`（版权素材、仅本地、gitignored）→ 复制进 `backend/media/character/portraits/` 本地使用，不入库。
- 无 Live2D 资源 → 只实现 Renderer Adapter 接口 + 能力检测 + 回退，不伪造 Live2D。
- Tailwind 4 CSS-first + DaisyUI 5，当前零自定义主题（`src/assets/main.css` 仅两行）。
- 前端 build 输出 `backend/static/frontend`，且 `backend/web/templates/index.html` 手工写死构建哈希 → 每次 build 后必须同步模板（构建脚本处理）。
- waitress WSGI 8 线程，SSE 每连接占线程；媒体 URL 公开；CORS 仅放行 5173。
- user store 已知 bug：logout 不清 profile；HomePageIndex 有失效拼写 class。

## 3. Design Tokens（CSS variables + DaisyUI 主题）

定义两套 DaisyUI 主题：`ailover-dark`（默认）、`ailover-light`，外加语义化 CSS 变量：

| Token | dark | light | 用途 |
|---|---|---|---|
| `--color-base` | #15101f | #faf7f2 | 页面底 |
| `--color-surface` | #1e1729 | #ffffff | 卡片/面板 |
| `--color-surface-2` | #271d35 | #f3ede6 | 次级面板 |
| `--color-text` | #f2ede7 | #2a2233 | 主文字（Warm Ivory / 深紫） |
| `--color-text-dim` | #a89fb8 | #6f6580 | 次要文字 |
| `--color-accent` | #c9a0dc | #8b6fc0 | 主强调（Soft Lavender） |
| `--color-rose` | #e8a0bf | #c76b8f | 次强调（Soft Rose） |
| 角色色 `--color-char-hika` | #e0607e | — | 绯华（蔷薇红） |
| 角色色 `--color-char-ayame` | #9b7ede | — | 菖蒲（鸢尾紫） |

- 字体：`--font-sans: "Noto Sans SC", system-ui…`；舞台字幕可用 `--font-display: "Noto Serif SC", serif`。
- 圆角：卡片 12px、面板 16px、按钮 10px、chip full——**不统一大圆角**。
- 阴影：三层 soft shadow（`--shadow-card / pop / stage`），深色下用环境光式内阴影。
- 动效：150/250/400ms 三档，`cubic-bezier(.22,.68,.35,1)`；全站尊重 `prefers-reduced-motion`。
- 断点沿用 Tailwind 默认；移动端基准 390×844 / 360×800，桌面 1440×900 / 1920×1080。

## 4. 组件分层（新增代码优先 TypeScript）

```
src/
├─ design/        按钮、面板、抽屉、骨架屏、头像等无业务组件
├─ stage/         CharacterStage、StaticPortraitRenderer、renderer adapter、状态徽标
├─ conversation/  消息列表、气泡、输入区、VN 字幕条、useConversation.ts（SSE+音频+状态机）
├─ audio/         麦克风、播放状态（复用 orderedAudio.js，不重写）
└─ stores/        user.js（修 bug）+ conversation 相关 composable
```

角色状态机：`idle | listening | thinking | speaking | interrupted | error`，
由真实事件驱动（VAD onSpeechStart→listening；SSE 打开无内容→thinking；音频在播→speaking；
stop→interrupted；error 帧→error），禁止关键词猜情绪。

## 5. 页面结构

- **AppShell**：桌面左侧 slim icon rail（首页/好友/创建/设置）；移动端顶品牌条 + 底部 tab。
- **首页**：精选角色 hero 区（background_image 大图 + photo，不拉伸）+ 搜索 + 角色卡网格
  + 最近聊天；骨架/空/错误三态；修复重复请求与卸载后更新竞态。
- **`/chat/:friendId` 工作区**：桌面三栏（rail | Character Stage | Conversation Panel）；
  Stage 占视觉中心（背景 cover + 立绘/头像渲染器 + 状态 + 最新字幕）。
- **沉浸模式**：Stage 全屏 + 视觉小说式底部半透明字幕框（角色名标签 + 流式文本），
  与普通模式**共用同一份 useConversation 状态**，切换不断流、不丢消息。
- **移动端**：上 Stage 下对话，历史抽屉化，输入框避让键盘 + safe-area。

## 6. 兼容与回归清单（每阶段完成后核对）

- [ ] 登录/注册/刷新免登录；logout 后状态干净
- [ ] SSE 流式文本 + 音频分段有序播放 + 停止（cleanup_complete 轮询）+ 重试
- [ ] 历史上翻（last_message_id 分页）、搜索、导出、清空、记忆管理面板
- [ ] 开场白与快捷回复逻辑（在 ChatHistory，不在后端）
- [ ] 语音开关 localStorage `ailover.voice`；VAD barge-in 打断
- [ ] 角色创建/编辑/删除、好友管理
- [ ] `npm run build` 后同步 `backend/web/templates/index.html` 哈希（脚本化）
- [ ] `npm test`（node --test）通过；新增纯逻辑（状态机/SSE 解析）补测试
- [ ] finetune_data/、数据库、igrations 不动

## 2026-10-20 素材复核与实际实现修正

- 用户确认仅使用本游戏提取素材，不使用原创示例角色。所有原创角色代码与前端图片引用已撤下。
- 游戏 Init_VariableADV.ks 的真实编号为绯华=2、菖蒲=8；先前本地 portrait_map 将 st1/st2 直接映射到两人，编号不正确。
- 游戏使用 body + face + accessory 分层，Macro_Stand.ks 在 dx=0/dy=0 合成。旧 sprites 并不是可直接展示的完整角色。
- 现有 scripts/tlg.py 的第8、12号色彩变换错误，导致黄色色块。已与 Kirikiri 官方 tvpgl.c 核对并修复，新增数学向量回归测试。
- scripts/prepare_game_stage.py 从本地 stimage.xp3、bgimage.xp3 可复现地产生两位游戏角色的 WebP 透明立绘、头像及场景背景；不写数据库、不触碰 finetune_data。
- 资源保存在 gitignored backend/media/character/stage，Django 展示接口兼容映射；缺少游戏资源的源码包仍回退到已有上传图。
- 实际组件使用 ChatWorkspace → CharacterStage / ChatHistory / InputField / ConversationManager。沿用 InputField 的既有 SSE、取消代际与 OrderedAudioPlayer，不另造平行播放器。
