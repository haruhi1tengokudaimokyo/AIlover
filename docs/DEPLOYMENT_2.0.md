# AIlover 2.0：运行与云端准备

## 本地使用现有账号和真实服务

在仓库根目录运行：

```powershell
cd D:\AIlover\frontend
npm run build
cd D:\AIlover
.venv/Scripts/python.exe scripts/prepare_game_stage.py
.venv/Scripts/python.exe backend/manage.py runserver 127.0.0.1:8000
```

访问 `http://127.0.0.1:8000/`。模型与语音仍使用现有 `.env` 配置；没有新增浏览器端密钥。游戏素材准备脚本读取本地游戏资源，输出到被 Git 忽略的 media 目录，不写数据库。角色卡 slug 为 `hika` / `ayame` / `mugi`；新增麦使用 `backend/manage.py seed_ousama --slug mugi`，完整材料与验证见 [麦的交付记录](MUGI_DELIVERY.md)。

前后端开发分开运行：Django 使用 8000，另一终端在 frontend 运行 `npm run dev`，访问 5173。Vite 默认代理到 8000。桌面版继续使用 `launcher.py` 和原有 PyInstaller spec；本轮没有重新生成 EXE。

## 隔离界面验收

```powershell
cd D:\AIlover
.venv/Scripts/python.exe scripts/preview_redesign.py --fixture-stream
```

该脚本以 SQLite backup API 复制现有数据库到临时目录，仅在副本创建 `redesign-preview / preview-only-2026` 测试账号。它不创建角色，沿用副本已有的游戏角色。

`--fixture-stream` 只注入本地确定性文字流，用于检查 SSE 界面、停止、取消与刷新；禁止外部模型调用，TTS 关闭。省略参数则用于无密钥错误反馈验收。两种模式都不代表真实模型效果或真实音质。

另一终端：

```powershell
cd D:\AIlover\frontend
$env:AILOVER_DEV_BACKEND='http://127.0.0.1:8001'
npm run dev -- --host 127.0.0.1 --port 5173
```

预览数据库位于启动日志显示的临时目录。图片复用项目 media 路径；预览中的聊天写入临时副本。退出预览服务不会删除真实数据库。

## 生产配置

生产环境显式设置 `DJANGO_SETTINGS_MODULE=backend.production`，桌面继续使用 `backend.settings`。生产配置不会由 DEBUG 自动推断。

```dotenv
DJANGO_SETTINGS_MODULE=backend.production
SECRET_KEY=use-a-new-long-random-secret-at-least-32-characters
ALLOWED_HOSTS=companion.example.com
CSRF_TRUSTED_ORIGINS=https://companion.example.com
CORS_ALLOWED_ORIGINS=https://companion.example.com
AI_LOVER_DATA_DIR=/srv/ailover/data
POSTGRES_DB=ailover
POSTGRES_USER=ailover
POSTGRES_PASSWORD=set-on-server-only
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_SSLMODE=require
```

若省略 POSTGRES_DB，仍使用 SQLite。切换数据库配置不会迁移旧数据；迁移前应备份并在新库演练，不要覆盖现有库。服务器私有环境文件中另外配置原有 API_KEY、API_BASE、MODEL 与 TTS 变量。

构建前端后，在服务器安装 `backend/requirements-production.txt`，按顺序运行：

```bash
cd backend
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --noinput
uvicorn backend.asgi:application --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

`scripts/deploy/nginx.conf` 提供 HTTPS 反向代理示例，需替换域名、证书和目录。SSE 关闭代理缓冲，读取超时 180 秒。`GET /api/health/` 检查数据库连通，不暴露模型密钥或版本细节。静态文件从 collectstatic 输出目录服务。

媒体仅开放展示目录，不能将整个 media 目录映射到公网。当前角色表没有“私有角色”字段：角色头像与背景属于现有公开角色大厅语义，用户聊天、记忆和导出仍需所有者权限；私密上传、付费素材和私有角色产品化需要额外的授权下载设计。本地游戏素材未取得公开分发许可，本轮保持本地使用，不自动上传或发布。

## 当前部署边界

- 使用单进程 ASGI：现有 generation registry 和取消状态在进程内。增加 workers 或部署多实例之前，需要共享任务/取消注册表与分布式会话锁。
- 云配置提供匿名 60/min、账号 120/min、聊天 12/min 的基本限流；同一好友保持现有单轮生成锁。这不是计费预算或严格日配额，多实例需共享缓存和更细的资源配额。
- ASGI 通过异步逐项桥接现有同步 SSE 生成器，避免 Django 将同步流整段缓冲。同步数据库/生成器仍占用线程，未完成高并发压测。
- 生产安全配置已通过本机 `check --deploy`。没有目标服务器、证书或 PostgreSQL 实例；未执行真实云部署。本机未安装 uvicorn，因此 ASGI 桥接经过单测，未声称在 uvicorn 上完成全链路验收。
- Live2D 没有真实模型与运行时，本轮只提供渲染能力选择和生命周期类型；静态模式完整可用，不需要 WebGL。
