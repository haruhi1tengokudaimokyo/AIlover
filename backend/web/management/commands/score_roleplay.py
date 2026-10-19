"""Validate explicit human ratings, never invent role-similarity scores."""
import json
import math
from pathlib import Path
from statistics import mean
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = '合并人工 0..4 评分并汇总；拒绝把 Mock 回复评为真实角色效果'

    def add_arguments(self, parser):
        parser.add_argument('--report', required=True)
        parser.add_argument('--scores', required=True)
        parser.add_argument('--output', required=True)

    def handle(self, *args, **options):
        report = json.loads(Path(options['report']).read_text(encoding='utf-8'))
        if report.get('offline'):
            raise CommandError('Mock 报告不能用于真实角色相似度评分')
        scores = json.loads(Path(options['scores']).read_text(encoding='utf-8')).get('scores')
        if not isinstance(scores, list) or len(scores) > 10000:
            raise CommandError('scores 必须是评分列表')
        cases = {(case['id'], case['variant']): case for case in report['cases']}
        seen, aggregates = set(), {}
        for rating in scores:
            key = (rating.get('id'), rating.get('variant'))
            if key not in cases or key in seen:
                raise CommandError('评分用例不存在或重复')
            seen.add(key)
            dimensions = rating.get('dimensions')
            if not isinstance(dimensions, dict) or not dimensions:
                raise CommandError('需要评分维度')
            allowed = cases[key].get('human_dimensions', {})
            for dimension, value in dimensions.items():
                if dimension not in allowed or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 4:
                    raise CommandError('评分维度需匹配报告，且分数为有限的 0..4 数字')
                allowed[dimension] = value
                aggregates.setdefault(key[1], {}).setdefault(dimension, []).append(value)
            cases[key]['human_score'] = {'dimensions': dimensions, 'method': 'explicit_human_rating'}
        report['human_aggregate'] = {variant: {dimension: {'mean': mean(values), 'n': len(values)}
                                             for dimension, values in metrics.items()} for variant, metrics in aggregates.items()}
        report['human_scoring_notice'] = '人工分数不是通用准确率，需报告样本、评审方法和模型配置。'
        target = Path(options['output'])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        self.stdout.write(f'已合并 {len(seen)} 个人工评分；未调用模型。')
