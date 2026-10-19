import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from web.documents.utils.retrieval_evaluation import evaluate
from web.documents.utils.story_retriever import dense_search


class Command(BaseCommand):
    help = '离线合成检索消融，不调用任何 API，不输出原作台词'

    def add_arguments(self, parser):
        parser.add_argument('--dataset')
        parser.add_argument('--output')
        parser.add_argument('--k', type=int, default=4)
        parser.add_argument('--data-dir', help='使用本地审核 bundle；dataset 可只含 cases/gold ID')
        parser.add_argument('--dense-provider', choices=['mock', 'off', 'real'], default='mock')
        parser.add_argument('--allow-api', action='store_true', help='显式允许真实 Embedding API')

    def handle(self, *args, **options):
        if options['k'] <= 0:
            raise CommandError('k must be positive')
        if options['dense_provider'] == 'real' and not options['allow_api']:
            raise CommandError('真实 Dense 需要 --allow-api；默认不消耗 API')
        path = Path(options['dataset']) if options['dataset'] else Path(settings.BASE_DIR) / 'evaluation/retrieval_synthetic.json'
        provider = None
        label = 'deterministic_mock'
        if options['dense_provider'] == 'real':
            provider = lambda *args: dense_search(*args)
            label = 'configured_embedding_and_lancedb'
        elif options['dense_provider'] == 'off':
            provider = lambda *args: []
            label = 'disabled'
        report = evaluate(json.loads(path.read_text(encoding='utf-8')), options['k'], options['data_dir'], provider, label)
        if options['output']:
            out = Path(options['output'])
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open('x', encoding='utf-8') as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
        self.stdout.write(json.dumps({name: result['aggregate'] for name, result in report['strategies'].items()}, indent=2))
