"""离线语料质量报告，保留文件与声音溯源，不推断人物设定。"""
import json
from collections import Counter
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = '离线检查原作台词重复、参考声音路径和场景覆盖，输出可审校的报告'

    def add_arguments(self, parser):
        parser.add_argument('--output', default=None, help='可选JSON输出路径')

    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR).parent
        report = {'version': 1, 'characters': []}
        for path in sorted((Path(settings.BASE_DIR) / 'web/documents/character_lines').glob('*.jsonl')):
            rows, invalid = [], []
            for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                try:
                    row = json.loads(raw)
                    if not isinstance(row.get('text'), str) or not row['text'].strip():
                        raise ValueError()
                    rows.append(row)
                except (ValueError, AttributeError):
                    invalid.append(number)
            counts = Counter(row['text'] for row in rows)
            voices = [row['voice'] for row in rows if row.get('voice')]
            missing = [voice for voice in voices if not (root / voice).is_file()]
            entry = {'slug': path.stem, 'lines': len(rows), 'invalid_lines': invalid,
                     'unique_texts': len(counts), 'duplicate_rows': sum(count - 1 for count in counts.values()),
                     'scene_count': len({row.get('file') for row in rows}),
                     'voice_rows': len(voices), 'missing_voice_count': len(missing),
                     'missing_voice_examples': missing[:10],
                     'review_samples': [rows[i] for i in range(0, len(rows), max(1, len(rows) // 12))][:12]}
            report['characters'].append(entry)
            self.stdout.write(f'{path.stem}: {len(rows)}条，重复{entry["duplicate_rows"]}条，场景{entry["scene_count"]}个，缺少语音{len(missing)}条')
        if options['output']:
            output = Path(options['output'])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            self.stdout.write(f'报告已保存：{output}')
