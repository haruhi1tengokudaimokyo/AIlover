"""Index verified local deliverables and application evidence; no model calls."""
from pathlib import Path
import shutil
from hotaru_training_common import json_read, json_write, sha

ROOT = Path(__file__).resolve().parents[1]


def main():
    checks = json_read(ROOT / 'AIlover_Hotaru_校验.json')
    for item in checks['packages']:
        if item['delivered_verifier']['status'] != 'passed' or sha(ROOT / item['file']) != item['sha256']:
            raise ValueError('Root delivery differs from the extracted, verified package')
    install = json_read(ROOT / 'docs/evaluation/hotaru-install.json')
    http = json_read(ROOT / 'docs/evaluation/hotaru-http-smoke.json')
    browser = json_read(ROOT / 'docs/evaluation/hotaru-browser.json')
    tests = json_read(ROOT / 'docs/evaluation/hotaru-automated-checks.json')
    checks.update(application_install=install, isolated_http=http, browser=browser, automated_checks=tests,
                  published_archive_hashes_rechecked=True)
    roots = [ROOT / 'extracted/characters/hotaru', ROOT / 'finetune_data/hotaru/llm', ROOT / 'backend/seed_assets/hotaru']
    files = {p for root in roots for p in root.rglob('*') if p.is_file() and 'runtime-preliminary-01' not in p.parts}
    files.update(p for p in (ROOT / 'backend/media/character/stage').glob('hotaru-*') if p.is_file())
    files.update([ROOT / 'backend/seed_cards/hotaru.json', ROOT / 'backend/web/documents/character_lines/hotaru.jsonl',
                  ROOT / 'finetune_data/hotaru/glossary.json', ROOT / 'finetune_data/hotaru/README.md'])
    manifest = {p.relative_to(ROOT).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(files)}
    extra_manifest = ROOT / 'finetune_data/hotaru/audit/local_handoff_sha256.json'
    json_write(extra_manifest, {'algorithm': 'SHA256', 'scope': 'new local runtime, original voice reference, art, glossary and LLM handoff extras', 'files': manifest})
    checks['local_extra_manifest'] = {'path': extra_manifest.relative_to(ROOT).as_posix(), 'sha256': sha(extra_manifest), 'files': len(manifest)}
    json_write(ROOT / 'AIlover_Hotaru_校验.json', checks)
    shutil.copyfile(ROOT / 'AIlover_Hotaru_校验.json', ROOT / 'finetune_data/hotaru/preparation-v1/AIlover_Hotaru_校验.json')
    text, tts = checks['text'], checks['tts']
    report = f'''# 水无月萤：完整本地交付

## 已接入应用

已创建角色 `hotaru`（ID {install['database_install']['character_id']}）及好友，使用《天津罪》真实立绘、头像、背景和七张额外原作差分。
首页四位同组件精选卡、普通/沉浸聊天、语音开关、结构化记忆、LangGraph与检索共用现有实现。
角色卡依据随游戏官方人物介绍；中文开场白与示例明确是产品改写，未冒充游戏台词。
原作主角为织部诚，现实用户不默认就是诚；独立的另一身份“ＯＲほたる”与orsn声音未合并。

运行时来源 {install['records']} 条，中文风格示例 {install['dialogue_examples']} 条。正文是汉化中文，日文另存。
现有 lore 文件为空，未从台词猜写新事实；官方人物设定在角色卡中，不把推断秘密加入长期记忆。
未配置真实适配音色时沿用通用中文服务音色，`HOTARU_VOICE`可接后续真实音色，当前不声称中文声音克隆完成。

安装前一致性备份：`{install['database_install']['backup']}`。
旧账号、角色、聊天、记忆逐表核对不变；旧Story行逐字节前缀保留，原目录另有备份。

## 中文文本与日语声音

|项目|实际结果|
|---|---|
|中文原作上下文样本|{text['canonical']}|
|训练/验证/测试|{text['splits'].get('train',0)} / {text['splits'].get('validation',0)} / {text['splits'].get('test',0)}|
|另写合成候选|{text['synthetic_pending']}条，待审，未进入正式训练|
|全部原生日语声音|{tts['raw_audio']}段 / {tts['raw_hours']:.6f}小时，全部实际解码|
|技术合格声音|{tts['accepted']}段 / {tts['accepted_hours']:.6f}小时|
|有原作日文台词的声音|{tts['script_linked_japanese_transcripts']}，其中5段说话人显示未知，隔离待审|
|严格身份下中日可靠对应|{tts['reliable_bilingual']}段|
|排除声音|{tts['excluded']}段，逐条记录原因|
|少样本集合|{tts['fewshot_files']}段 / {tts['fewshot_minutes']:.5f}分钟，全量同时保留|
|重新选择的参考|{tts['references']}段，保留准确来源日文，仍待试听|
|中文目标文字|{tts['zh_target_texts']}条，映射全部{text['canonical']}个V3目标|
|真实中文录音/中文监督配对|0 / 0|

原声中16段没有任何已解密日文剧本消息引用，未猜转录；另5段有台词但显示为“？？？”，保留原位置与身份差异。
“可靠对应”指同源PS3文件、指令位置、消息ID、调用参数、voice ID与双方SHA的结构匹配，不是人工听审证书。
音频数值通过也不能证明没有BGM、多人重叠、字幕与实际朗读差异或截断；人工确认数为0，相关项目为未测。
可以开始日语角色适配的数据审查，之后可用多语种底模尝试日语参考→中文目标。
真正中文语音监督训练仍需目标音色的真实中文录音及准确逐句中文转写。

## 可找到的文件

首层两个ZIP为正式交付，均已实际重新解压，运行仓库校验器及随包校验工具；每包有全文件SHA256清单。

|文件|字节数|SHA256|
|---|---:|---|
'''
    for item in checks['packages']:
        report += f"|{item['file']}|{item['bytes']}|`{item['sha256']}`|\n"
    report += '''
其他同等交接材料：

- `extracted/characters/hotaru/`：原始记录、干净台词、来源、60条参考候选、120条抽样、自称/称呼统计。
- `finetune_data/hotaru/llm/source/`：双语来源及真实中文前序场景。
- `finetune_data/hotaru/llm/output/`：中文ShareGPT train/validation/test与登记；`glossary.json`在角色数据首层。
- `backend/seed_assets/hotaru/voice_ref.ogg`和`.txt`：原始日语参考，绝不冒充中文声音。
- `finetune_data/hotaru/preparation-v1/verified_delivery/`：实际重新解压通过的文本包与语音包。
- `source/variants`与`script_versions.json`：保留原/补丁版本供复核，不当作额外重复训练数据。
- `docs/HOTARU_INTEGRATION.md`、`HOTARU_ASSETS.md`、`HOTARU_TRAINING_PIPELINE.md`：接入、素材、训练准备及上游方法依据。

各ZIP的README说明数据使用与`tools/verify.py`命令。语音包用`paths`在包外生成训练机器本地绝对路径.list。
源数据、旧三个角色和原有10个训练ZIP保持不变。游戏原文、图片、声音与交付包均只留本机，不自动公开上传。

## 验证范围

Django后端123项、前端22项、运行时保护3项、训练规则14项、真实PS3篡改拦截9项均通过；类型检查与生产构建通过。
10张原作图像验证可解码、尺寸、透明通道、路径和来源哈希。实际HTTP验证搜索/好友/聊天页/图像均正常。
浏览器实际点击验证四角色首页、萤聊天、沉浸舞台和记忆面板，截图为`docs/screenshots/hotaru-{home,chat}.png`。
所有浏览器/HTTP检查在隔离数据库副本中，未写入真实聊天。没有训练模型、TTS推理、ASR或付费生成请求。
这些软件检查和材料结构检查不等于真实模型角色还原或声音质量评测；未伪造效果分数。
'''
    (ROOT / 'AIlover_Hotaru_完整交付.md').write_text(report, encoding='utf-8')
    print('Final Hotaru report and published ZIP hashes verified; extra local data SHA manifest created.')


if __name__ == '__main__':
    main()
