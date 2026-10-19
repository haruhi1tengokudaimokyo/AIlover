# 可重复、可审核的本地原作数据流水线

## 已实际构建的范围

真实输入为 `extracted/scenario_all/scenario/main` 下 109 个 `.ks`，其他 UI / debug / engine 脚本没有列为剧情覆盖。本轮最终本地 bundle：`extracted/story_builds/phase1-v4`。包含游戏文本的文件已忽略，不应加入 Git、日志、公开报告或桌面分发。

真实统计见 `evaluation/corpus-summary.json`：22,050 条结构化记录；3,272 条风格示例（hika 1,960 / ayame 1,312）；12,489 条语音映射，其中 8,382 条未找到本地音频；重复文本 295 条；87 条缺少说话人。所有路线和情绪均为 null。剧情事实 0 条，因为尚无人工核实 sidecar。增量构建复用了全部 109 个未改变的源文件。

所有记录都有不确定性：源脚本有 118 处跳转类引擎命令，其路径语义没有解释；另有 132 处未知标签。这不表示文本不可读，也不表示恢复了完整时间线。文件内的物理顺序可追踪，跨文件 chronology / 路线 / 动态变量不作推断。scene_id 仅是文件与标签的组合，不等于已验证地点。

## 数据契约

`records.jsonl` 每条具有 `id`、相对 `source_file`、`source_location.line_start/line_end`、源文件 SHA256、解码方式、文件内 sequence、speaker、character、text、raw_text、voice_id、scene_id、route_id、label、branch、segment、evidence_type、emotion、uncertainties、context。

ID 由相对路径、位置和同行序号确定；同一构建重复运行稳定，重复文字仍保留不同来源。插入前置行会改变下游位置 ID，审核需重新绑定；不声称支持任意编辑后的语义 ID 稳定。来源 SHA256 用来拒绝过期审核。UTF-8、BOM UTF-16 和 CP932 支持严格解码，失败会审计而非静默替换。

上下文最多前后各两条，含旁白，仅在同一 segment 内；标签、条件和无法解释的跳转切断 segment。行内标记保留在 raw_text；visible text 去除标记并标记不确定。未闭合台词、未平衡条件和未知标签记入审计，不执行任何游戏脚本。

| 文件 | 用途 |
| --- | --- |
| `dialogue_examples.jsonl` | 目标角色的原文与真实邻接上下文，沿用已有清洗规则，情绪不猜测，style_labels 默认空 |
| `story_knowledge.jsonl` | 人工核实事实与证据 ID；没有审核时为空，不能把原文台词直接宣称为事实 |
| `voice_manifest.jsonl` | voice_id、实际存在的本地 audio_path、来源；不复制音频、不训练、不与知识向量混用 |
| `audit.json` | 字段缺失、重复、不确定数、每文件覆盖、未识别结构 |
| `parse_cache.jsonl` | 未校正的解析记录与解析器版本；增量复用，不从旧审核结果反向生成原文 |

清洗是旧项目的启发式行级过滤，不等于完整内容审核；上下文也使用清洗规则筛选。由于保留新捕获的上下文与来源，不覆盖原有 1,910 / 1,303 条单句数据集。

## 本地构建与启用（PowerShell，仓库根目录）

```powershell
.\.venv\Scripts\python.exe scripts/build_story_data.py --output extracted/story_builds/my-v1
# 下一次使用一个新目录；不覆盖任何现有构建。
.\.venv\Scripts\python.exe scripts/build_story_data.py --output extracted/story_builds/my-v2 --previous extracted/story_builds/my-v1 --review my-review.json
$env:STORY_DATA_DIR = 'D:\AIlover\extracted\story_builds\phase1-v4'
$env:ROLEPLAY_RAG_MODE = 'story'
.\.venv\Scripts\python.exe backend/manage.py build_story_index
.\.venv\Scripts\python.exe backend/manage.py doctor
.\.venv\Scripts\python.exe backend/manage.py runserver
```

构建先写同级 `.story-partial-*` 目录，再 rename 发布完整 bundle。已存在目标拒绝覆盖；进程中断留下的 staging 不会被激活，可在确认其为本次生成的目录后人工清理。增量按文件内容哈希与 parser_version 复用；文件删去不再进入新构建，修改文件重新解析。旧构建保留，可切回其路径。

运行时默认路径为 DATA_DIR/story_data，脚本必须显式给 `--output`。本机已首次构建 `backend/story_data`，复用v4全部109个缓存；默认聊天无需另指定路径，用户环境配置未修改。重建使用新目录后显式切换，禁止覆盖已有bundle。

## 审核 sidecar

合成示例（字段值不是游戏事实）：

```json
{
  "corrections": {
    "SOURCE_RECORD_ID": {
      "source_sha256": "CURRENT_SOURCE_FILE_SHA256",
      "speaker": "已核实称呼",
      "character": "hika",
      "emotion": "concerned"
    }
  },
  "lore": [{
    "id": "reviewed-fact-id",
    "text": "人工根据证据确认的事实正文",
    "character": "hika",
    "route_id": null,
    "scene_id": null,
    "keywords": ["人工确认的检索关键词"],
    "source_ids": ["SOURCE_RECORD_ID"],
    "source_hashes": {"SOURCE_RECORD_ID": "CURRENT_SOURCE_FILE_SHA256"},
    "reviewed": true
  }]
}
```

允许校正 speaker / character / text / route_id / emotion / scene_id，保留原文和来源。speaker改动同步更新资料类型，未显式给character时重算已知别名。校正记录、Lore和audit保存review_sha256；原始缓存不带人工修改。必须匹配源哈希，过期修正与不合格事实输出审计。Sidecar只读，重建重新应用。`reviewed=true`是人工声明，不能证明判断正确。

Dense 构建会消耗配置 Embedding 服务额度，只有显式执行以下命令才构建新表：

```powershell
.\.venv\Scripts\python.exe backend/manage.py build_story_index --dense --data-dir extracted/story_builds/phase1-v4
$env:STORY_DENSE_ENABLED = 'true'
```

需要匹配提供商、模型、维度并校准距离阈值。本轮仅在真实 LanceDB + Mock Embedding 下验证存取，没有调用付费 Embedding。`build_style_index` 继续服务旧单句表；`parse_scenario.py` 保留旧字段并增加来源结构，`build_character_data.py` 透传 provenance。旧脚本默认写旧路径，不用于本轮不可变构建。

回退：设置 `ROLEPLAY_RAG_MODE=legacy` 或 `off`，不需要数据库回滚或删除新数据。Phase 1 未增加 Django migration；`makemigrations --check --dry-run` 已验证无缺失迁移。
