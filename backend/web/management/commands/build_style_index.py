# -*- coding: utf-8 -*-
"""
为角色台词库构建向量索引（风格 RAG 的离线步骤，需要可用的嵌入模型 API）。

用法：
    python manage.py build_style_index            # 为所有有台词库的角色构建
    python manage.py build_style_index --slug hika
"""
from django.core.management.base import BaseCommand

from web.documents.utils import style_retriever
from web.models.character import Character


class Command(BaseCommand):
    help = '为角色台词库构建 LanceDB 向量索引（style_<slug> 表）'

    def add_arguments(self, parser):
        parser.add_argument('--slug', type=str, default=None, help='只构建指定角色')

    def handle(self, *args, **options):
        slugs = [options['slug']] if options['slug'] else list(
            Character.objects.exclude(slug='').values_list('slug', flat=True).distinct()
        )
        if not slugs:
            self.stdout.write('没有找到带 slug 的角色，请先运行 seed_ousama')
            return
        for slug in slugs:
            n = style_retriever.build_index(slug)
            self.stdout.write(self.style.SUCCESS(f'{slug}: 已写入 {n} 条台词向量'))
