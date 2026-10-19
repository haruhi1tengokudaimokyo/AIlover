"""离线检查运行配置，不打印密钥，不调用付费服务。"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand
from web.models.character import Character
from web.models.friend import Message
from web.documents.utils.style_retriever import table_exists


class Command(BaseCommand):
    help = '检查模型配置、角色台词、参考语音和索引，不联网、不显示密钥'

    def handle(self, *args, **options):
        self.stdout.write(f'数据目录：{settings.DATA_DIR}')
        self.stdout.write(f'模型：{os.getenv("MODEL", "deepseek-v3.2")}')
        self.stdout.write('模型密钥：' + ('已配置' if os.getenv('API_KEY', '').strip() else '未配置，无法真实对话'))
        try:
            host = urlsplit(os.getenv('API_BASE', 'https://api.openai.com/v1')).hostname or '地址格式不正确'
        except ValueError:
            host = '地址格式不正确'
        self.stdout.write(f'模型服务：{host}')
        self.stdout.write('语音：' + ('开启，需可用语音服务/音色' if os.getenv('TTS_ENABLED', 'true').lower() == 'true' else '关闭，纯文字'))
        self.stdout.write(f'角色数：{Character.objects.count()}，成功对话记录：{Message.objects.count()}')
        from web.models.friend import MemoryItem, MemoryJob
        from web.views.friend.message.memory.structured import structured_enabled
        self.stdout.write(f'记忆模式：{"structured" if structured_enabled() else "legacy"}；'
                          f'有效条目 {MemoryItem.objects.filter(status="active").count()}；'
                          f'待恢复任务 {MemoryJob.objects.filter(status__in=["pending", "running", "failed"]).count()}')
        from web.documents.utils.story_retriever import bundle_path, read_channel
        self.stdout.write(f'角色检索模式：{os.getenv("ROLEPLAY_RAG_MODE", "story")}；剧情数据目录：{bundle_path()}')
        for channel in ('lore', 'style'):
            try:
                self.stdout.write(f'{channel}：{len(read_channel(channel))} 条；Dense 默认关闭，需显式配置与构建')
            except (ValueError, OSError):
                self.stdout.write(f'{channel}：数据不可读，请重新构建')
        for card in sorted((Path(settings.BASE_DIR) / 'seed_cards').glob('*.json')):
            slug = json.loads(card.read_text(encoding='utf-8'))['slug']
            corpus = Path(settings.BASE_DIR) / 'web/documents/character_lines' / f'{slug}.jsonl'
            count = sum(1 for raw in corpus.read_text(encoding='utf-8').splitlines() if raw.strip()) if corpus.exists() else 0
            reference = Path(settings.BASE_DIR) / 'seed_assets' / slug / 'voice_ref.opus'
            try:
                index = '已建立' if table_exists(slug) else '未建立（使用本地词法检索）'
            except Exception:
                index = '读取失败（使用本地词法检索）'
            self.stdout.write(f'{slug}：台词 {count} 条；参考音频 {"存在" if reference.exists() else "缺失"}；向量索引 {index}')
        self.stdout.write('此检查不验证远程密钥有效性、模型权限或语音克隆效果。')
