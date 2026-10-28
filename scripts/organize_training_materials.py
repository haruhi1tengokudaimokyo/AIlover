"""Collect private training deliveries without moving build inputs or caches."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '训练材料'
ROLES = [('hika', 'Hika', '绯华'), ('ayame', 'Ayame', '菖蒲'),
         ('mugi', 'Mugi', '麦'), ('hotaru', 'Hotaru', '水无月萤')]


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def main():
    if DEST.exists():
        raise ValueError('Destination already exists; inspect it rather than overwriting user files')
    DEST.mkdir()
    manifest = {}

    def copy(source, relative):
        source = Path(source)
        if not source.is_file():
            raise ValueError('Missing material: ' + str(source))
        target = DEST / relative
        if not target.resolve().is_relative_to(DEST.resolve()) or target.exists():
            raise ValueError('Unsafe or duplicate destination')
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = sha(source)
        shutil.copyfile(source, target)
        if target.stat().st_size != source.stat().st_size or sha(target) != expected:
            raise ValueError('Copy verification failed: ' + str(relative))
        manifest[Path(relative).as_posix()] = {'bytes': target.stat().st_size, 'sha256': expected,
                                             'original_path': source.relative_to(ROOT).as_posix()}

    def copy_tree(source, relative):
        if not source.is_dir():
            return
        for path in sorted(source.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                copy(path, Path(relative) / path.relative_to(source))

    role_links = []
    for number, (slug, english, chinese) in enumerate(ROLES, 1):
        folder = f'{number:02d}_{chinese}_{english}'
        text = f'AIlover_{english}_Text_V3.zip'
        voice = f'AIlover_{english}_TTS_Preparation_V1.zip'
        copy(ROOT / text, f'{folder}/中文文本/{text}')
        copy(ROOT / voice, f'{folder}/日语语音/{voice}')
        print('Copied and SHA256 checked: ' + chinese, flush=True)
        extras = Path(folder) / '补充资料'
        copy(ROOT / 'backend/seed_cards' / (slug + '.json'), extras / '角色卡.json')
        copy_tree(ROOT / 'backend/seed_assets' / slug, extras / '原始参考音频与来源')
        source = ROOT / 'extracted/characters' / slug
        for path in sorted(source.glob('*')):
            if path.is_file() and path.suffix.lower() in ('.json', '.jsonl', '.txt', '.md', '.csv'):
                copy(path, extras / '来源与台词抽样' / path.name)
        if slug in ('mugi', 'hotaru'):
            copy_tree(ROOT / 'finetune_data' / slug / 'llm', extras / 'LLM交接目录')
            for name in ('README.md', 'glossary.json', 'source_summary.json', 'verification.json'):
                path = ROOT / 'finetune_data' / slug / name
                if path.is_file():
                    copy(path, extras / name)
        role_links.append(f'|{chinese}|[中文文本]({folder}/中文文本/{text})|[日语语音]({folder}/日语语音/{voice})|')

    common = '05_通用说明与质检'
    for path in sorted(ROOT.glob('AIlover_*')):
        if not path.is_file():
            continue
        if path.name == 'AIlover_TTS_Finetune_Preparation_V1.zip':
            copy(path, f'{common}/前三角色合并语音包/{path.name}')
        elif path.suffix.lower() in ('.md', '.json', '.csv'):
            location = '06_历史旧版_不用于本轮训练' if path.name.startswith('AIlover_全中文方案_') else common
            copy(path, f'{location}/{path.name}')
        elif path.suffix == '.zip' and '_v2_' in path.name:
            copy(path, f'06_历史旧版_不用于本轮训练/{path.name}')
    copy_tree(ROOT / 'finetune_data/llm', '06_历史旧版_不用于本轮训练/早期双角色文本目录')
    for role in ('mugi', 'tts'):
        source = ROOT / 'finetune_data' / role
        for path in sorted(source.glob('*')):
            if path.is_file() and path.suffix in ('.list', '.md', '.json'):
                copy(path, f'06_历史旧版_不用于本轮训练/旧清单_{role}/{path.name}')
    history_reports = ROOT / 'share/training-handoff'
    for path in sorted(history_reports.glob('*/*')):
        if path.is_file() and path.suffix.lower() in ('.md', '.json', '.csv'):
            copy(path, Path('06_历史旧版_不用于本轮训练/旧交接报告') / path.relative_to(history_reports))
    for path in sorted((ROOT / 'docs').glob('*')):
        if path.is_file() and path.suffix == '.md' and any(word in path.name.upper() for word in ('HOTARU', 'MUGI', 'TEXT_CORPUS', 'TTS_', 'AMATSUTSUMI')):
            copy(path, Path(common) / '方法与来源说明' / path.name)
    for path in sorted((ROOT / 'scripts').glob('*')):
        if path.is_file() and (any(word in path.name for word in ('training', 'tts', 'text_corpus', 'text_v3', 'hotaru', 'amatsutsumi', 'handoff'))
                              or path.name in ('xp3.py', 'parse_scenario.py', 'build_character_data.py', 'mugi_filter.py', 'prepare_mugi_training.py')):
            copy(path, Path('07_提取与校验脚本/scripts') / path.name)

    index = '''# AIlover 训练材料总目录

四位角色的正式训练交付和补充资料已集中在本文件夹。直接按下面的角色取包即可。

|角色|当前中文文本包|当前日语语音包|
|---|---|---|
''' + '\n'.join(role_links) + '''

## 怎么拿

- 文本微调：取对应角色的中文文本V3 ZIP，解压后看README与sft/dataset_info.json。
- 声音适配：取对应角色的日语语音V1 ZIP，解压后看README、.list与tools/verify.py。
- 参考原声、角色卡、台词抽样和额外LLM目录：看该角色的“补充资料”。ZIP本身已包含完整来源、分区、参考清单和质检，不需要再找工作缓存。
- 完整交付报告、SHA256、人工审核表、提取方法：看“05_通用说明与质检”。
- “前三角色合并语音包”包含绯华、菖蒲、麦，内容与三个独立包重合；不含萤，不要作为额外样本重复训练。
- “06_历史旧版”只作对照存档，当前训练以V3文本/V1语音为准。旧版的路径和说明保留历史原样。
- “07_提取与校验脚本”是源码备份，重建时在原AIlover仓库运行；可独立使用的校验器在各正式ZIP内部。

## 数据状态

中文文本与日语声音分开管理。当前没有真实中文录音监督集：日语音频只能配ja标签和实际日文转写。
中文译文用于对齐与未来中文合成目标，不能替代日语音频的转写。语音技术合格仍需人工听审。

## 原目录与完整性

本目录里的正式包和补充资料均为实体副本，已逐文件核对SHA256，复制到其他硬盘也能携带。
原位置保留，避免破坏现有构建脚本和应用。处理缓存、旧包的重复解压副本、原始游戏封包没有再次复制。
需要重建时：原作提取在D:/AIlover/extracted，工作数据在D:/AIlover/finetune_data，历史解压材料在D:/AIlover/share/training-handoff。
“文件清单_SHA256.json”列出每份复制材料的相对位置、大小、SHA256及原位置；本说明与清单本身不纳入递归自校验。
'''
    (DEST / '00_先看这里.md').write_text(index, encoding='utf-8')
    (DEST / '文件清单_SHA256.json').write_text(json.dumps({'algorithm': 'SHA256', 'files': manifest,
        'copied_files': len(manifest), 'total_bytes': sum(r['bytes'] for r in manifest.values()),
        'all_copies_sha256_verified': True, 'original_files_moved_or_deleted': False}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'folder': str(DEST), 'files': len(manifest), 'bytes': sum(r['bytes'] for r in manifest.values()), 'status': 'all copies verified'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
