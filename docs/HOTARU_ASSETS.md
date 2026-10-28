# 水无月萤原作视觉资产

入口：`.venv/Scripts/python.exe -B -X utf8 scripts/prepare_hotaru_assets.py`。
只提取、解码、裁切和缩放真实游戏图片，不使用生成式图片，不修改游戏或原有三角色资产。

主立绘来自 `data/pack/stand.cpz` 的 `04_ほたる/st-hot_a102.pb3`，穿原作制服；与随游戏的 `manual/img/ch05.jpg` 角色介绍图目视对照确认身份。PB3 差分通过官方 GARbro 解码其真实基底，不重新绘制表情。

输出在 `backend/media/character/stage/`：

- `hotaru-portrait.webp`：删除透明空边的原立绘。
- `hotaru-avatar.webp`：同一张立绘的头像裁切。
- `hotaru-background.webp`：来自 `bg.cpz/pb3/bg110a.pb3` 的原作暖色咖啡馆内景。只作舞台视觉背景，不声称是角色居所或指定剧情地点。
- `hotaru-{neutral,smile,speaking,closed-eyes-smile,surprised,eyes-closed,blushing}.webp`：七个原作图像差分。
- `hotaru-expressions.json`：候选差分清单；英文名称描述画面，非原作官方情绪标签，不构成动画或口型模型。
- `hotaru-provenance.json`：原始归档、PB3 成员、手册、解码库和输出 SHA256，尺寸、透明通道、选择依据与旧角色资产哈希复核。

现有三位角色的舞台消费接口是静态 portrait/avatar/background；新角色按相同接口接入。额外差分保留为可追溯素材，界面是否动态使用以当前前端实现为准，不将文件存在描述为已完成动态表情或口型驱动。

## 解码依赖

使用 [GARbro 官方固定发行版 1.5.44](https://github.com/morkt/GARbro/releases/tag/v1.5.44)，MIT 许可，原许可留在 DLL 同目录。其 [CPZ 实现](https://github.com/morkt/GARbro/blob/master/ArcFormats/Cmvs/ArcCPZ.cs) 和 [PB3 实现](https://github.com/morkt/GARbro/blob/master/ArcFormats/Cmvs/ImagePB3.cs) 负责原作格式。

固定便携文件：`GARbro-v1.5.44.2904.rar`。
SHA256：`c0e64b881f967e0a1473127b1d181c0808068a47e99d8b5f1fbe2d99a6b2ed53`。

便携库解压在 `extracted/amatsutsumi/tools/GARbro/`。脚本使用本机 .NET Framework 编译 `scripts/amatsutsumi_garbro.cs` 为只读 CLI；不会启动游戏或 GARbro GUI，不向外上传原作数据。

CLI 支持 list / extract（默认解压外层资源与 PS2 容器）/ image / image-file / image-batch。PB3 基底引用包含相对路径，批量图像先提取同一原始目录，再用 image-file 或 image-batch 解码，保持差分对基底的真实引用。

提取源缓存及归档索引在 `extracted/amatsutsumi/assets/`。脚本复跑会比较已有解压成员与再次读出的字节；已有输出 WebP 若不同则拒绝覆盖，防止替换手动改过的素材。

## 复核

```powershell
.venv/Scripts/python.exe -B -X utf8 scripts/prepare_hotaru_assets.py --verify-only
```

这会实际读取所有 WebP，检查哈希、尺寸、角色透明通道，并重新核对原始 stand.cpz/bg.cpz。首次构建还会冻结并核对现有角色的全部舞台资产，确认新增角色没有改变旧图片。
