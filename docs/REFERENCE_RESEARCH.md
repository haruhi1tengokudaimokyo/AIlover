# 重构参考与兼容性核对

检视日期：2026-10-19 / 20。通过官方仓库文件与文档阅读实现，没有复制参考项目的角色、美术、标识或 UI 源码。以下版本是检视到的仓库 manifest 版本，不等同于声明所有分发渠道的最新稳定版本。

| 项目 | 实际查看的实现 | 对 AIlover 的取舍 |
|---|---|---|
| [AIRI](https://github.com/moeru-ai/airi) | [stage-web/index.vue](https://github.com/moeru-ai/airi/blob/main/apps/stage-web/src/pages/index.vue)、[stage-ui/package.json](https://github.com/moeru-ai/airi/blob/main/packages/stage-ui/package.json) | 检视版本 0.12.0-beta.5；Vue、Pinia、业务组件与 primitives 分层。借鉴舞台占主视野、独立移动输入区域与 viewport 跟随，沿用本项目 Vue 3，不移植其 monorepo。MIT。 |
| [Open-LLM-VTuber-Web](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web) | [layout.tsx](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/main/src/renderer/src/layout.tsx)、[use-interrupt.ts](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/main/src/renderer/src/hooks/utils/use-interrupt.ts)、use-audio-task.ts | 检视版本 1.2.1；借鉴打断时停止音频、清空队列及更新角色/字幕状态的协同，不移植 React/Electron 实现。其前端当前 [LICENSE](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web/blob/main/LICENSE) 是 Open-LLM-VTuber License 1.0，基于 Apache 2.0 加附加条件；不能简单按后端 README 的 MIT 概括前端，部分商业用途另有条件。 |
| [WebGAL](https://github.com/OpenWebGAL/WebGAL) | [Stage.tsx](https://github.com/OpenWebGAL/WebGAL/blob/main/packages/webgal/src/Stage/Stage.tsx)、[TextBox.tsx](https://github.com/OpenWebGAL/WebGAL/blob/main/packages/webgal/src/Stage/TextBox/TextBox.tsx) | 检视 engine manifest 4.6.6；借鉴人物、音频、名称字幕和文字区域分层，以及可读性与生命周期管理。不引入脚本播放器、Redux、Pixi 或逐字二次打字动画。MPL-2.0。 |

辅助项核对：

- [Reka UI](https://www.reka-ui.com/docs/overview/introduction) 是 Vue primitives；[VueUse](https://vueuse.org/guide/) 提供 Vue composables。没有新增这两项依赖，本轮已有 DaisyUI 5 + 原生 dialog 足够，避免为了少量弹层再叠 UI 框架。未获取可可靠核验的最新 npm 版本，因此没有填写猜测版本号。
- [CubismWebSamples](https://github.com/Live2D/CubismWebSamples) 当前查看的 develop README 说明兼容 Cubism 5.3，Core 不包含在仓库，需要另外获取。SDK、Core 和模型素材的许可需分别核对。AIlover 当前没有 `.model3.json` / `.moc3` 资源，因此未安装运行时、未接入模型，也未承诺口型同步。
- 本机实际保留 Vue 3.5、Vite 7、Pinia 3、Tailwind 4、DaisyUI 5、Django 6.0.8；构建与类型检查直接验证现有锁定环境，没有把参考项目的 React、UnoCSS、Pixi 依赖混入本项目。

没有声称运行过上述完整演示；本轮浏览器实测对象是本地 AIlover。

## 游戏立绘的实际修复依据

本地游戏 `Init_VariableADV.ks` 确认角色编号 2=绯华、8=菖蒲；`Init_VariableSTAND.ks` 提供服装组合；`Macro_Stand.ks` 提供 base → face → accessory 在原画布原点合成的次序。这些游戏脚本与提取图只保存在被 Git 忽略的本地目录，没有放入交付源码。

发现现有 TLG 解码器第 8、12 号色彩变换对蓝通道错误叠加，造成黄色块状偏色。对照 [Kirikiri 官方 tvpgl.c](https://github.com/krkrz/krkrz/blob/master/visual/tvpgl.c) 核对数学变换后修复，并用官方 C 解码器在本地编译的诊断结果逐字节比对四个输入图像，全部一致。诊断源码与二进制留在 gitignored 的本地目录；应用不依赖 gcc 或诊断 DLL。
