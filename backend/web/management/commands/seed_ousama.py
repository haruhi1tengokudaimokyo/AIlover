# -*- coding: utf-8 -*-
"""
一键创建《王様恋愛》角色卡：佐藤绯华（hika）、藤丘菖蒲（ayame）。

用法：
    python manage.py seed_ousama                  # 绑定到第一个注册用户
    python manage.py seed_ousama --username bob   # 绑定到指定用户

角色卡内容来自 backend/seed_cards/<slug>.json：
    name / profile / greeting / quick_replies / voice_env / voice_default

可选素材（backend/seed_assets/<slug>/，存在则自动使用）：
    photo.jpg        角色头像
    background.jpg   聊天背景图
    voice_ref.opus   声音复刻参考音频（供上传到百炼控制台，见 README）
    voice_ref.txt    参考音频对应台词文本

音色：在百炼控制台「声音复刻」上传 voice_ref 音频得到音色 ID 后，
填入环境变量 HIKA_VOICE / AYAME_VOICE 并重新运行本命令即可生效。
"""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from web.models.character import Character
from web.models.friend import SystemPrompt
from web.models.user import UserProfile

ROLEPLAY_PROMPT = (
    "你正在进行沉浸式角色扮演，扮演下方【角色卡】描述的角色，与用户对话。规则：\n"
    "1. 始终以角色身份回复，绝不跳出角色，绝不提及自己是 AI、语言模型或程序；\n"
    "2. 回复就是角色说出口的话：口语化、简短（一般 1~3 句），"
    "不要包含动作描写、心理描写、旁白、Markdown 或列表；\n"
    "3. 你的回复会被实时语音合成朗读给用户，请像真人说话一样自然，情绪要体现在语气和用词上；\n"
    "4. 结合【长期记忆】延续你与用户之间的羁绊与过往经历；"
    "用户透露的称呼、喜好、约定要记在心里并在合适时呼应。\n"
    "5. 【台词风格参考】是角色在原作中的真实台词（日语原文），用来校准语气、口癖和情绪节奏；"
    "模仿其语感，但回复必须使用中文，且不要直接照搬参考台词的内容。\n"
)

MEMORY_PROMPT = (
    "你是记忆整理助手。根据【原始记忆】和【最近对话】，更新角色与用户之间的长期记忆。要求：\n"
    "1. 只记录对长期陪伴有价值的信息：用户的称呼、喜好、习惯、重要事件、约定、关系进展、情绪状态；\n"
    "2. 删除过时或不再准确的内容，合并重复内容；\n"
    "3. 用第三人称简明扼要地书写，总长度不超过 400 字；\n"
    "4. 直接输出更新后的记忆文本本身，不要输出任何解释或前后缀。\n"
)

# 每位角色的占位图配色：(发色, 瞳色, 发饰色, 背景顶部色, 背景底部色)
PLACEHOLDER_COLORS = {
    'hika': ((196, 69, 54), (230, 170, 60), (250, 220, 120), (252, 242, 238), (246, 214, 205)),
    'ayame': ((120, 90, 160), (90, 130, 200), (200, 190, 230), (244, 240, 250), (216, 210, 238)),
}


class Command(BaseCommand):
    help = '创建《王様恋愛》绯华、菖蒲角色卡与默认系统提示词'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default=None, help='角色所属用户的用户名')

    def handle(self, *args, **options):
        # 1. 系统提示词（仅当不存在时创建）
        if not SystemPrompt.objects.filter(title='回复').exists():
            SystemPrompt.objects.create(title='回复', order_number=1, prompt=ROLEPLAY_PROMPT)
            self.stdout.write('已创建系统提示词「回复」')
        if not SystemPrompt.objects.filter(title='记忆').exists():
            SystemPrompt.objects.create(title='记忆', order_number=1, prompt=MEMORY_PROMPT)
            self.stdout.write('已创建系统提示词「记忆」')

        # 2. 找到作者
        username = options['username']
        if username:
            user = User.objects.filter(username=username).first()
            if not user:
                raise CommandError(f'用户 {username} 不存在，请先在应用里注册')
        else:
            user = User.objects.order_by('id').first()
            if not user:
                raise CommandError('还没有任何注册用户，请先在应用里注册一个账号，再运行本命令')
        profile, _ = UserProfile.objects.get_or_create(user=user)

        # 3. 逐个角色卡创建/更新
        cards_dir = Path(settings.BASE_DIR) / 'seed_cards'
        import os
        for card_path in sorted(cards_dir.glob('*.json')):
            card = json.loads(card_path.read_text(encoding='utf-8'))
            if 'slug' not in card:
                continue
            slug = card['slug']
            character, created = Character.objects.get_or_create(
                author=profile, name=card['name'],
                defaults={'profile': card['profile']},
            )
            character.profile = card['profile']
            character.slug = slug
            character.greeting = card.get('greeting', '')
            character.quick_replies = json.dumps(card.get('quick_replies', []), ensure_ascii=False)
            character.voice = os.getenv(card.get('voice_env', ''), '') \
                or character.voice or card.get('voice_default', 'longanyang')

            assets = Path(settings.BASE_DIR) / 'seed_assets' / slug
            colors = PLACEHOLDER_COLORS.get(slug, PLACEHOLDER_COLORS['hika'])
            if not character.photo:
                photo = assets / 'photo.jpg'
                if photo.exists():
                    with photo.open('rb') as f:
                        character.photo.save(f'{slug}_photo.jpg', File(f), save=False)
                else:
                    character.photo.save(f'{slug}_photo.png', self._placeholder_photo(colors), save=False)
            if not character.background_image:
                bg = assets / 'background.jpg'
                if bg.exists():
                    with bg.open('rb') as f:
                        character.background_image.save(f'{slug}_bg.jpg', File(f), save=False)
                else:
                    character.background_image.save(f'{slug}_bg.png', self._placeholder_bg(colors), save=False)
            character.save()
            self.stdout.write(self.style.SUCCESS(
                f'{"已创建" if created else "已更新"}角色「{card["name"]}」（slug={slug}，音色={character.voice}）'
            ))

        self.stdout.write(
            '接下来在应用里「添加好友」选择角色即可开始聊天。\n'
            '想让角色用自己的声音说话：把 seed_assets/<slug>/voice_ref.opus 上传到百炼控制台\n'
            '「声音复刻」得到音色 ID，填进 .env 的 HIKA_VOICE / AYAME_VOICE 后重新运行本命令。'
        )

    @staticmethod
    def _placeholder_photo(colors):
        """生成角色配色的占位头像"""
        from io import BytesIO
        from PIL import Image, ImageDraw
        hair, eye, ribbon, _, _ = colors
        img = Image.new('RGB', (512, 512), (245, 240, 232))
        d = ImageDraw.Draw(img)
        d.ellipse((56, 56, 456, 456), fill=hair)                  # 发
        d.ellipse((96, 150, 416, 470), fill=(255, 238, 224))      # 脸
        d.ellipse((150, 240, 220, 320), fill=eye)                 # 左眼
        d.ellipse((292, 240, 362, 320), fill=eye)                 # 右眼
        d.ellipse((170, 258, 192, 282), fill=(255, 255, 255))     # 高光
        d.ellipse((312, 258, 334, 282), fill=(255, 255, 255))
        d.arc((216, 340, 296, 400), start=10, end=170, fill=(150, 80, 80), width=8)  # 嘴
        d.polygon([(256, 30), (236, 90), (276, 90)], fill=ribbon)  # 发饰
        buf = BytesIO()
        img.save(buf, 'PNG')
        buf.seek(0)
        return File(buf, name='photo.png')

    @staticmethod
    def _placeholder_bg(colors):
        """生成角色配色的渐变占位背景"""
        from io import BytesIO
        from PIL import Image, ImageDraw
        _, _, _, top, bottom = colors
        w, h = 1280, 720
        img = Image.new('RGB', (w, h))
        d = ImageDraw.Draw(img)
        for y in range(h):
            t = y / h
            d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
        for cx, cy, r in [(180, 140, 60), (1050, 200, 90), (820, 560, 70), (300, 600, 100)]:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255), width=6)
        buf = BytesIO()
        img.save(buf, 'PNG')
        buf.seek(0)
        return File(buf, name='bg.png')
