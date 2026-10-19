from django.core.management.base import BaseCommand, CommandError
from web.documents.utils.story_retriever import build_dense, read_channel


class Command(BaseCommand):
    help = '检查剧情与风格数据；显式 --dense 才调用 Embedding 并构建独立 LanceDB 表'

    def add_arguments(self, parser):
        parser.add_argument('--data-dir')
        parser.add_argument('--dense', action='store_true')
        parser.add_argument('--channel', choices=['lore', 'style', 'all'], default='all')

    def handle(self, *args, **options):
        for channel in (('lore', 'style') if options['channel'] == 'all' else (options['channel'],)):
            try:
                count = build_dense(channel, options['data_dir']) if options['dense'] else len(read_channel(channel, options['data_dir']))
                self.stdout.write(f'{channel}: {count} records; dense={options["dense"]}')
            except Exception as exc:
                raise CommandError(f'{channel}: index unavailable ({type(exc).__name__})') from None
