"""生成用于项目审阅的轻量包，不包含运行时账号数据或真实环境配置。"""
import hashlib
import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'share'
TEXT_EXTENSIONS = {'.py', '.vue', '.js', '.mjs', '.ts', '.css', '.html', '.json', '.jsonl', '.md', '.txt', '.svg'}
FORBIDDEN_PARTS = {'__pycache__', 'node_modules', '.git', '.venv', 'media', 'backups', 'evaluations',
                   'static', 'staticfiles', 'lancedb_storage', 'lancedb_style', 'vad'}
FORBIDDEN_PARTS.update({'story_data', 'story_builds', 'lancedb_story', 'seed_assets', 'character_lines', 'system-private'})

INTRO = '''# AIlover 项目代码审阅包

这是可安装的源码验收包，不是已验收的 Windows EXE。
包含全部应用/工具源码、依赖配置、迁移、测试、文档与合成评测 fixture。
不包含原作台词、剧本、语音、用户数据库、真实环境配置或私有真实模型报告。

先阅读 docs/WEB_GPT_ACCEPTANCE.md 和 docs/INSTALL_REVIEW.md，
再阅读 PROJECT_TECHNICAL_HIGHLIGHTS.md 和 docs/ARCHITECTURE.md、
DATA_PIPELINE.md、MEMORY.md、VOICE.md、EVALUATION.md。
完成声明应以实际源码、测试和明确标注的报告为准；
Mock 结果不能用于宣称真实角色还原度、云端性能或全双工能力。

只有显式 --include-private-corpus 才加入原作台词和参考资产；
此时产物为私有本地材料，发布前必须审核素材授权与隐私。
'''


def collect_files(include_private_corpus=False):
    forbidden = FORBIDDEN_PARTS - ({'seed_assets', 'character_lines'} if include_private_corpus else set())
    files = set()
    for folder in ['backend/backend', 'backend/web', 'backend/seed_cards', 'backend/evaluation',
                   'backend/seed_assets', 'frontend/src', 'frontend/scripts', 'frontend/tests', 'scripts', 'docs']:
        for path in (ROOT / folder).rglob('*'):
            relative = path.relative_to(ROOT)
            if not path.is_file() or path.is_symlink() or any(part in forbidden for part in relative.parts):
                continue
            if path.suffix not in TEXT_EXTENSIONS and not (folder == 'backend/seed_assets' and path.name == 'voice_ref.opus'):
                continue
            if path.name.startswith('.env') or path.suffix in {'.sqlite3', '.db', '.pkl', '.log'}:
                continue
            if folder == 'docs' and path.suffix == '.json':
                payload = json.loads(path.read_text(encoding='utf-8-sig'))
                if isinstance(payload, dict) and payload.get('requires_human_review') and not payload.get('offline'):
                    continue  # Real generated replies remain private by default.
            files.add(path)
    # PROJECT_CORPUS_AUDIT.json contains quoted original review_samples, not just counts.
    for name in ['README.md', 'PROJECT_STATUS.md', 'USER_NEXT_STEPS.md',
                 '.env.example', '.gitignore', 'launcher.py', 'ailover.spec', 'backend/manage.py',
                 'backend/requirements.txt']:
        path = ROOT / name
        if path.is_file():
            files.add(path)
    if (ROOT / 'PROJECT_TECHNICAL_HIGHLIGHTS.md').is_file():
        files.add(ROOT / 'PROJECT_TECHNICAL_HIGHLIGHTS.md')
    for relative in ('backend/requirements-lock-windows.txt', 'frontend/public/favicon.ico'):
        path = ROOT / relative
        if path.is_file():
            files.add(path)
    for path in (ROOT / 'frontend').iterdir():
        if path.is_file() and (path.suffix in TEXT_EXTENSIONS or path.name == '.gitignore'):
            files.add(path)
    if include_private_corpus:
        for path in (ROOT / 'extracted/characters').rglob('*.txt'):
            if path.is_file():
                files.add(path)
    for path in files:
        if path.stat().st_size > 5 * 1024 * 1024:
            raise ValueError(f'Unexpected large file: {path.relative_to(ROOT)}')
        if path.suffix in TEXT_EXTENSIONS or path.name == '.env.example':
            text = path.read_text(encoding='utf-8-sig')
            # 只报文件名，不把疑似真实密钥输出到日志。
            if re.search(r'\bsk-[A-Za-z0-9_-]{24,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text):
                raise ValueError(f'Potential credential in {path.relative_to(ROOT)}; inspect before sharing')
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-private-corpus', action='store_true', help='显式加入私有原作台词/参考资产；不要未经授权分享')
    options = parser.parse_args()
    OUTPUT.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    archive_path = OUTPUT / f'AIlover-review-{stamp}.zip'
    text_path = OUTPUT / f'AIlover-review-{stamp}.txt'
    files = collect_files(options.include_private_corpus)
    merged = [INTRO, '\n\n===== 文件目录 =====\n']
    merged.extend(path.relative_to(ROOT).as_posix() + '\n' for path in files)
    first = ['PROJECT_STATUS.md', 'README.md', 'USER_NEXT_STEPS.md']
    ordered = sorted(files, key=lambda path: (first.index(path.name) if path.parent == ROOT and path.name in first else 10,
                                            path.relative_to(ROOT).as_posix()))
    for path in ordered:
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix not in TEXT_EXTENSIONS and path.name not in {'.env.example', 'ailover.spec', '.gitignore'}:
            continue
        if path.name == 'package-lock.json':
            continue  # lock文件在ZIP里保留，文本阅读版不重复展开依赖树。
        content = path.read_text(encoding='utf-8-sig')
        if path.suffix == '.jsonl':
            lines = content.splitlines()
            content = f'[文本阅读版仅显示前20行，共{len(lines)}行；ZIP内保留完整文件]\n' + '\n'.join(lines[:20])
        merged.append(f'\n\n===== FILE: {relative} =====\n{content}\n')
    text_path.write_text(''.join(merged), encoding='utf-8')
    manifest = {'purpose': 'AIlover project review', 'private_corpus_included': options.include_private_corpus, 'files': [
        {'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size,
         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files],
        'excluded': ['game archives', 'bulk voices/images', 'dependencies', 'build outputs', 'runtime user data', 'real .env', 'logs']}
    with ZipFile(archive_path, 'x', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr('AIlover-review/00_READ_FIRST.md', INTRO)
        archive.writestr('AIlover-review/PROJECT_REVIEW.txt', text_path.read_bytes())
        archive.writestr('AIlover-review/FILE_MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for path in files:
            archive.write(path, 'AIlover-review/' + path.relative_to(ROOT).as_posix())
    with ZipFile(archive_path) as archive:
        assert archive.testzip() is None, 'ZIP integrity failure'
        entries = archive.namelist()
        assert len(entries) == len(set(entries))
        assert len(entries) == len(files) + 3
        forbidden = FORBIDDEN_PARTS - ({'seed_assets', 'character_lines'} if options.include_private_corpus else set())
        assert all(not any(part in forbidden for part in Path(name).parts) for name in entries)
        assert all(not name.endswith(('.sqlite3', '.db', '.exe', '.pkl', '.log')) for name in entries)
        assert all(Path(name).name != '.env' for name in entries)
        for path in files:
            assert archive.read('AIlover-review/' + path.relative_to(ROOT).as_posix()) == path.read_bytes()
    assert archive_path.stat().st_size < 512 * 1024 * 1024
    checksum_path = archive_path.with_suffix('.zip.sha256')
    checksum_path.write_text(hashlib.sha256(archive_path.read_bytes()).hexdigest() + '  ' + archive_path.name + '\n', encoding='ascii')
    print(json.dumps({'zip': str(archive_path), 'zip_bytes': archive_path.stat().st_size,
                      'text': str(text_path), 'text_bytes': text_path.stat().st_size,
                      'sha256_file': str(checksum_path), 'source_files': len(files), 'archive_integrity': 'passed'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
