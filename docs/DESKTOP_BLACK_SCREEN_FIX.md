# Windows 桌面黑屏修复与交付验收

日期：2026-10-28。此前只检查了首页 HTTP 200，没有确认 Vue 真正挂载，验收不足。

## 实际复现与修复

在生产服务中复现整个页面只显示深色背景。浏览器控制台明确报错：`Unable to preload CSS for /assets/HomePageIndex-Devx5XxN.css`。HTML 入口脚本已被同步到 Django static 路径，但 Vite 内部懒加载 CSS 仍按根 `/assets/` 加载，导致 `router.isReady()` 失败、应用没有挂载。

修复内容：

- Vite 生产 base 为 `/static/frontend/`，开发 base 保留 `/`。
- Vue 页面路由基址保持 `/`，与静态资产前缀分开。
- 构建后模板同步支持生产前缀；首页禁止缓存，防止沿用旧入口。
- 初始化失败时显示明确提示，避免再次只留空白背景。
- EXE 自检不再只检查 HTTP 200，还核对入口 JS/CSS、生产预加载前缀、20 个懒加载资源及其 MIME 类型。

## 已实际执行

- 真正启动根目录 EXE，在原生 AIlover 桌面窗口中确认新版首页、四角色卡片、游戏立绘与背景。
- 在原生窗口点击“登录”，确认登录表单完整显示；另在浏览器确认首页控制台没有错误。
- 本机截图：`docs/screenshots/desktop-home-fixed.png`、`desktop-login-fixed.png`。截图仅作本机验收，不自动上传角色图像到 Git。
- 后端完整142项测试通过，包含专门针对这次生产静态路径问题的回归测试。
- 前端22项测试、Vue类型检查、Vite生产构建通过。
- 百炼四角色真实文本与流式接入已在上轮通过；本轮修复不重复调用收费模型。

本轮没有使用用户密码登录原账号，也没有把首页/登录页验收称为所有登录后流程的完整验收。角色训练语音仍待托管，当前四角色为文本模式。

## 使用与重建

根目录 `AIlover启动.exe` 使用现有 `.venv`、`launcher.py`、后端数据库、媒体和被忽略的 `.env`，不能只把 EXE 单独移动到其它位置。源码与同一份启动 EXE 一起提交到 GitHub；Key、数据库和训练素材不上传。

双击即可打开。若旧窗口仍在运行，可从任务栏恢复它，或关闭旧窗口后再打开。启动日志在 `runtime/desktop/`。

重建使用 PyInstaller 的 `scripts/quick_launch.py` 入口，图标使用 `frontend/public/favicon.ico`；所有路径应使用绝对路径。`--verify` 只启动本地自检后端，检查完自动停止该子进程。
