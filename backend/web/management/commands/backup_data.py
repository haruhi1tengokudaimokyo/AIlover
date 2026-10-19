"""SQLite一致性快照和媒体备份，不包括密钥与游戏素材。"""
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import localtime, now


class Command(BaseCommand):
    help = '备份本机数据库和媒体到 data/backups，不包含.env或游戏本体'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--output-dir', default=None, help='备份输出目录（默认数据目录/backups）')

    def handle(self, *args, **options):
        source = Path(settings.DATABASES['default']['NAME'])
        if not source.is_file():
            raise CommandError('数据库不存在，请先初始化应用')
        output = Path(options['output_dir']) if options['output_dir'] else Path(settings.DATA_DIR) / 'backups'
        if output.resolve().is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
            raise CommandError('备份目录不能位于媒体目录内')
        output.mkdir(parents=True, exist_ok=True)
        path = output / f'ailover-{localtime(now()).strftime("%Y%m%d-%H%M%S-%f")}.zip'
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / 'db.sqlite3'
            with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(snapshot)) as destination:
                original.backup(destination)
            with ZipFile(path, 'x', compression=ZIP_DEFLATED) as archive:
                archive.write(snapshot, 'db.sqlite3')
                media = Path(settings.MEDIA_ROOT)
                if media.exists():
                    for file in sorted(media.rglob('*')):
                        if file.is_file() and not file.is_symlink() and not file.name.startswith('.env') and file.suffix != '.env':
                            archive.write(file, 'media/' + file.relative_to(media).as_posix())
                archive.writestr('manifest.json', json.dumps({'version': 1, 'created_at': now().isoformat(),
                    'includes': ['database', 'media'], 'excludes': ['API keys', 'game assets', 'vector indexes']}, ensure_ascii=False))
        self.stdout.write(self.style.SUCCESS(f'备份已保存：{path}'))
        self.stdout.write('备份包含账号、聊天和记忆，请妥善保存。恢复前先关闭应用，不要覆盖仍在使用的数据库。')
