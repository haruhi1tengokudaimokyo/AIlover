"""Offline validation by default; executions use a disposable evaluation database."""
from django.core.management.base import BaseCommand
from web.views.friend.message.chat.graph import ChatGraph
from web.documents.utils.roleplay_evaluation import run_evaluation


class Command(BaseCommand):
    help = '默认校验；--offline 独立数据库执行 Mock 消融；--run 才调用付费模型'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--run', action='store_true')
        group.add_argument('--offline', action='store_true')
        parser.add_argument('--slug', choices=['hika', 'ayame', 'mugi', 'hotaru'], default='hika')
        parser.add_argument('--case')
        parser.add_argument('--output')
        parser.add_argument('--variant', choices=['baseline', 'legacy', 'story', 'story_memory', 'all'], default='story')
        parser.add_argument('--include-extended', action='store_true')
        parser.add_argument('--history-pairs', type=int, default=10)
        parser.add_argument('--identity-mode', choices=['real_user', 'protagonist'])

    def handle(self, *args, **options):
        return run_evaluation(self, options, ChatGraph)
