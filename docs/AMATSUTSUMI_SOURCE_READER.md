# 《天津罪》来源提取与独立复核

本次使用本机已有游戏文件，只读输入，不执行游戏程序、不运行 ASR 或模型。脚本是 `scripts/amatsutsumi_extract.py`；所有解包文件、审计和音频位于 `extracted/amatsutsumi/`。

## 实际格式与证据

- 原版 `data/pack/*.cpz` 实际签名为 **CPZ6**。使用官方 GARbro 1.5.44 库和只读 CLI `scripts/amatsutsumi_garbro.cs` 读取目录及成员。SHA256、目录项、偏移、压缩大小和解包成员 SHA 均保存。
- 原日文 PS3 来源为 `script.cpz`，官方 `update.cpz` 内的 `スクリプト` 成员覆盖同名基础文件；基础版本不删除，来源账包含两版 SHA。
- 汉化 `Pk/Scripts.pk` 与根 `Scriptspk.UPD` 为 PKP：12 字节头、176 字节目录项，UTF16 文件名，成员 raw-deflate。成员为 **保留 LZSS 但跳过 PS2A 加密层** 的 PS3；本项目通过精确解压长度、字符串边界和逐条调用核对确认，未照搬日语加密参数。
- 汉化基础 86 份、补全更新 27 份都保留。有效汉化采用 UPD 同名覆盖；另保留未选版本的来源清单，不能把不同版本或不同译文默认为相同文本。
- PS3 为 `PS2A` 头，字符串表由头中的 jump count、代码长度和字符串长度精确定位。字符串引用必须落在有效 C 字符串边界。

上游方法：[GARbro CPZ 实现](https://github.com/morkt/GARbro/blob/master/ArcFormats/Cmvs/ArcCPZ.cs)、[PS2A 原始解析工具](https://github.com/xmoezzz/CMVS-Engine/tree/master/Ps2TextDumper)、[PS3 字符串引用实现](https://github.com/xmoezzz/CMVS-Engine/tree/master/Ps3TextDumper)。本项目没有将逐个相邻字符串直接猜成一组台词。

## 台词、角色与上下文

普通消息调用包含三项字符串参数（实际台词、声音文件名、显示说话人）和四项整数参数，调用字节为 `10 04 43 00`；另存在三字符串、两整数参数的特殊 `40/42` 调用，分别保留调用类别与来源。中日对齐同时要求同源文件名、消息 ID、全部整数参数、声音文件名和调用类别相同，不依赖语义相似。

每条记录保留两端的源 SHA、opcode 偏移、字符串偏移、原始文字和规范化文字，ID 带 `amatsutsumi_` namespace。日语 ruby 真读音取 reading，强调用的点状 ruby 保留基础文字；原始 ruby 仍可逐字复核。中文中未更改的日文原字节不会冒充已翻译中文。

上下文 segment 仅含 **连续消息调用字节码**，任意非消息指令间隙都会另起 segment。因此不会跨未知跳转、镜头或其他指令拼接上下文。`scene_id` 是明确标注的文件内 linear block，不假装恢复原作语义场景或路线。场景显性内容筛查为自动关键词筛查整个 block，仍待人工审查。

原声音频 `hosn*.ogg` 在归档的 `04_ほたる`；`ＯＲほたる` 则有独立说话人编号 11、`orsn` 前缀和 `05_ＯＲほたる` 声音目录，未混入水无月萤音色。某些声音的字幕显示名为 `？？？`，显示名与声音目录必须同时保留。汉化误把名字写成其他角色的条目用 `localized_speaker_conflict` 保留，不能静默修正原文后再称完全对应。

`verify_ledger(package_root, rows)` 不信任 JSON 标签：重新读取包内原始解包 PS3，核对两端声音、角色编号、文字、偏移、来源 SHA、稳定 ID、连续段、安全筛查和完整 opcode 覆盖。删除一条源记录也会失败。自动复核不证明声音实际逐字等同字幕，也不能证明翻译语义完全正确。

## 复现

```powershell
.venv/Scripts/python.exe -B -X utf8 scripts/amatsutsumi_extract.py --extract-zh
# 原版 CPZ 由 AmatsutsumiGarbro.exe extract 读取；不要用新输出覆盖不同解包结果。
.venv/Scripts/python.exe -B -X utf8 scripts/amatsutsumi_extract.py --align --voice-inventory --audit-sources
.venv/Scripts/python.exe -B -X utf8 -m unittest discover -s scripts -p test_amatsutsumi_source_reader.py
```

## 上游许可

PS2A 解析/解压算法参考 GARbro（Copyright (C) 2015-2019 by morkt）及 xmoezzz/CMVS-Engine，均为 MIT 许可。GARbro 官方二进制附带 LICENSE.txt 原文。以下保留 MIT 条款：

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
