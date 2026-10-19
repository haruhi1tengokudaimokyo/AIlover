from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils.timezone import now
from web.models.friend import MemoryJob
from web.views.friend.message.memory.structured import process_job


class Command(BaseCommand):
    help = '恢复/处理持久记忆任务；保守规则提取，不调用 API，不依赖守护线程'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--retry-failed', action='store_true', help='显式重置已耗尽重试的失败任务；来源/版本边界仍校验')

    def handle(self, *args, **options):
        if options['retry_failed']:
            MemoryJob.objects.filter(status='failed', attempts__gte=3).update(attempts=0, retry_at=now(), status='pending', error_code='')
        ids = list(MemoryJob.objects.filter(Q(status__in=['pending', 'failed'], retry_at__lte=now(), attempts__lt=3)
                   | Q(status='running', lease_until__lte=now())).order_by('pk').values_list('pk', flat=True)[:max(0, min(options['limit'], 1000))])
        completed = sum(process_job(pk) for pk in ids)
        self.stdout.write(f'examined={len(ids)} completed={completed}; no API calls')
