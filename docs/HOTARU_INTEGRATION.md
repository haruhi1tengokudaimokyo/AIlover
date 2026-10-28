# 《天津罪》水无月萤：前后端与 Agent 接入

角色标识为 `hotaru`，显示名水无月萤，原文水無月ほたる。沿用现有三位角色的工作区、静态立绘舞台、流式对话、可中断语音、结构化记忆和双通道检索，不创建一套与旧角色脱节的聊天实现。

## 人物来源

角色卡基于本机游戏随附官方人物介绍：

- `[無碼] 天津罪（アマツツミ）/manual/index.html` 第 474 行，标题水無月ほたる；SHA256 `8c64bd210340dec2c92908427ffaae327ed82601c73412629c3251940833e456`。
- `manual/img/ch05.jpg`，直接查看原图读取介绍；SHA256 `2a63a3e12e04c69e015e794b2b98a0398901464e18becbb4823414e62c53c76c`。

可确认的性格是表情丰富、善于活跃气氛、容易与人亲近，言行自由但也有理性、善于商量的一面；兴趣为风景摄影，喜欢烟花、购物与海，不喜欢药、智能手机和噪音。言灵对她不起作用属于作品设定。未用这些偏好推断病史或路线结局。

`backend/seed_cards/hotaru.json` 中五组中文对话与开场白是依据人物介绍编写的产品改写，明确标记为非游戏原句。默认称呼用户为“你”，不把用户指定成原作主角织部诚，不沿用麦的女仆身份或称呼，也不预设恋爱关系。真实原作上下文和汉化译文由独立提取流水线供给，不能用这五个改写反向充当游戏证据。

## 接入路径

| 部分 | 实现 |
|---|---|
| 角色创建 | `seed_amatsutsumi` 复用现有受保护种子逻辑，仅处理 hotaru；缺真实游戏美术则失败 |
| 旧角色保护 | `seed_ousama` 默认仍只处理原来的 hika/ayame/mugi，不扫描新增跨游戏卡 |
| 声音设置 | `HOTARU_VOICE`，默认现有通用中文服务音色；这不表示中文角色克隆完成 |
| 首页 | 四位可用同一精选立绘卡，四卡时两列显示；搜索仍使用公共结果网格 |
| 聊天舞台 | 原有 `CharacterStage`、`ChatWorkspace` 和真实播放状态机，不增加伪口型或模型 |
| Agent | 通用 LangGraph → 来源限定的 lore/style 检索 → 有预算的资料上下文 → 真实用户记忆 |
| 身份模式 | `real_user` / `protagonist` 继续走公共 ContextBuilder，均不把未知路线当共同经历 |
| 旧风格检索 | 独立 `character_lines/hotaru.jsonl`；中日词法映射支持汉化正文 |
| Story RAG | 合并到旧 bundle 的新副本，旧数据逐字节前缀保留，旧 lore 完全不变；不自动推断新 lore |
| 评测入口 | `preview_roleplay`、`evaluate_roleplay` 接受 hotaru；默认不调用模型 |

语音失败或未配置时使用已有文字降级；原作日语参考、训练材料和真实可用的中文声音模型是不同产物。

## 安装与保护

训练流水线应先在 `extracted/characters/hotaru/` 提供 `source_records.jsonl`、`dialogue_examples.jsonl`、`lines_clean.jsonl`。CMVS 的来源位置保留真实二进制偏移/指令位置，不伪造 KAG 的 `.ks` 文件或物理行。

```powershell
.venv/Scripts/python.exe -B scripts/install_hotaru_runtime.py --output extracted/story_builds/four-characters-hotaru-新目录 --install
```

安装器只以当前开发数据库 `backend/db.sqlite3` 为目标，先做 SQLite 一致性备份，再只新增 hotaru 角色与好友；逐表验证所有旧行不变。不向真实用户数据库写测试聊天。旧 Story 目录保留为 `backend/story_data-backup-before-hotaru-*`，新副本的每个旧记录保持原始字节，旧角色身份不更改。

安装器拒绝重复覆盖已有 hotaru 语料，重建时应选择新的输出目录，先检查已有安装与备份。新角色 ID 带游戏命名空间，若与旧语料碰撞会停止。

素材由 `scripts/prepare_hotaru_assets.py` 从原作提取，输出 `backend/media/character/stage/hotaru-{portrait,avatar,background}.webp` 和独立来源记录。三个图片通过 `portrait_map.json` 与同一个角色 slug 关联。不能用自创图片代替原作立绘。

## 验证命令

```powershell
.venv/Scripts/python.exe -B backend/manage.py test web --noinput
.venv/Scripts/python.exe -B -m unittest discover -s scripts -p test_hotaru_runtime.py
npm --prefix frontend test
npm --prefix frontend run build
.venv/Scripts/python.exe -B backend/manage.py preview_roleplay --slug hotaru --message 今天有点累，陪我聊会儿吧 --output docs/evaluation/context-preview-hotaru.json
.venv/Scripts/python.exe -B backend/manage.py benchmark_retrieval --slug hotaru --output docs/evaluation/retrieval-hotaru.json
```

前端生产构建自动同步 Django 模板。自动测试验证四角色展示、角色/资料隔离、缺素材拒绝安装、旧消息和记忆保护、真实公共上下文路径及两种身份模式；它们不证明真实模型的角色还原、声音相似度或汉化语义完全正确。

最终安装的真实计数、备份路径和旧行保护结果记录于 `docs/evaluation/hotaru-install.json`；接口、资源和上下文报告分别另存，不把 Mock 契约当成真实 LLM/TTS 效果。
