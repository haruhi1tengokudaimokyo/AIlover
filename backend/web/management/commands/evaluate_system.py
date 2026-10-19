"""One reproducible offline report bundle, no automatic paid evaluations."""
import json
import os
import time
from io import StringIO
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from web.documents.utils.story_retriever import read_channel


class Command(BaseCommand):
    help = '统一离线检索/对话/记忆/语音报告；不请求 API、不写应用聊天数据库'

    def add_arguments(self, parser):
        parser.add_argument('--output-dir')
        parser.add_argument('--story-data-dir')

    def handle(self, *args, **options):
        directory = Path(options['output_dir']) if options['output_dir'] else Path(settings.DATA_DIR) / 'evaluations' / f'system-{time.time_ns()}'
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise CommandError('输出目录已存在，请选择新目录，避免覆盖报告') from None
        self.stdout.write('运行离线检索消融（严格 Dense，无 API）')
        call_command('evaluate_retrieval', output=str(directory / 'retrieval.json'), stdout=StringIO())
        self.stdout.write('运行四种对话消融及结构化记忆（独立临时数据库）')
        call_command('evaluate_roleplay', offline=True, include_extended=True, variant='all',
                     output=str(directory / 'conversation.json'), stdout=StringIO())
        self.stdout.write('运行 Mock 语音分段/时序消融')
        call_command('evaluate_voice', output=str(directory / 'voice.json'), stdout=StringIO())
        latency = None
        if options['story_data_dir']:
            self.stdout.write('测量真实本地语料 Sparse 延迟（不评价召回质量）')
            call_command('benchmark_retrieval', data_dir=options['story_data_dir'], iterations=60,
                         output=str(directory / 'latency.json'), stdout=StringIO())
            latency = json.loads((directory / 'latency.json').read_text(encoding='utf-8'))
        retrieval = json.loads((directory / 'retrieval.json').read_text(encoding='utf-8'))
        conversation = json.loads((directory / 'conversation.json').read_text(encoding='utf-8'))
        voice = json.loads((directory / 'voice.json').read_text(encoding='utf-8'))
        checks = [value for case in conversation['cases'] for turn in case['turns']
                  for value in (turn.get('memory_state_checks') or {}).values()]
        lore_count = len(read_channel('lore', options['story_data_dir'])) if options['story_data_dir'] else 0
        summary = {'version': 1, 'mode': 'offline_contract_evaluation', 'api_calls': 0,
                   'retrieval_synthetic': retrieval['synthetic'], 'retrieval': {name: data['aggregate'] for name, data in retrieval['strategies'].items()},
                   'conversation_combinations': len(conversation['cases']),
                   'conversation_failed_turns': sum('error_type' in turn for case in conversation['cases'] for turn in case['turns']),
                   'memory_checks': len(checks), 'memory_checks_passed': sum(checks),
                   'isolated_database_deleted': conversation['isolated_database_deleted'],
                   'voice_text_complete': all(run['text_complete'] for run in voice['runs']),
                   'voice_cleanup_complete': all(run['cleanup_complete'] for run in voice['runs']),
                   'local_sparse_latency': latency, 'real_lore_records': lore_count,
                   'human_role_scores': None, 'real_model_quality_verified': False,
                   'missing_conditions': ['人工审核原作 facts/gold', '真实模型与 Embedding 评测',
                                          '人工角色相似度盲评', '真实云语音/麦克风/网络验证', 'Windows EXE/WebView 验收']}
        (directory / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(f'报告目录：{directory}；记忆检查 {sum(checks)}/{len(checks)}；真实效果仍未评分。')
        if summary['conversation_failed_turns'] or not all(checks) or not summary['voice_cleanup_complete']:
            raise CommandError('离线契约检查失败，请查看报告；没有消耗 API')
