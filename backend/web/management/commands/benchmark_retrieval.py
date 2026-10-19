"""Local measured latency, no prompts, raw script text, or user data in reports."""
import json
import statistics
import time
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from web.documents.utils.story_retriever import StoryRetriever


class Command(BaseCommand):
    help = '测量本地 Sparse 冷/热检索延迟，不调用 API 或读取用户消息'

    def add_arguments(self, parser):
        parser.add_argument('--data-dir')
        parser.add_argument('--slug', default='hika')
        parser.add_argument('--iterations', type=int, default=30)
        parser.add_argument('--output')

    def handle(self, *args, **options):
        if not 1 <= options['iterations'] <= 1000:
            raise CommandError('iterations must be 1..1000')
        retriever = StoryRetriever('style', root=options['data_dir'])
        queries = ['今天做什么料理？', '工作好累，想休息', '量子色动力学公式']
        def run(query):
            started = time.perf_counter()
            hits, trace = retriever.retrieve(options['slug'], query, strategy='sparse')
            return (time.perf_counter() - started) * 1000, len(hits), trace
        cold, count, trace = run(queries[0])
        samples, counts = [], []
        for index in range(options['iterations']):
            elapsed, count, _ = run(queries[index % len(queries)])
            samples.append(elapsed)
            counts.append(count)
        ordered = sorted(samples)
        report = dict(strategy='sparse', channel='style', slug=options['slug'],
                      iterations=options['iterations'], queries='fixed_food_rest_unrelated',
                      cold_ms=cold, warm_p50_ms=statistics.median(samples),
                      warm_p95_ms=ordered[min(len(ordered) - 1, int(.95 * len(ordered)))],
                      hit_counts=counts, cold_status=trace['status'],
                      quality_claim=False, network_calls=0)
        if options['output']:
            path = Path(options['output'])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as handle:
                json.dump(report, handle, indent=2)
        self.stdout.write(json.dumps(report, indent=2))
