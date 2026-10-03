# -*- coding: utf-8 -*-
"""
一键创建「丛雨」（《千恋＊万花》）角色卡与系统提示词。

用法：
    python manage.py seed_murasame                  # 绑定到第一个注册用户
    python manage.py seed_murasame --username bob   # 绑定到指定用户

可选素材（存在则自动使用）：
    backend/seed_assets/murasame/photo.jpg        角色头像
    backend/seed_assets/murasame/background.jpg   聊天背景图
"""
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
)

MEMORY_PROMPT = (
    "你是记忆整理助手。根据【原始记忆】和【最近对话】，更新角色与用户之间的长期记忆。要求：\n"
    "1. 只记录对长期陪伴有价值的信息：用户的称呼、喜好、习惯、重要事件、约定、关系进展、情绪状态；\n"
    "2. 删除过时或不再准确的内容，合并重复内容；\n"
    "3. 用第三人称简明扼要地书写，总长度不超过 400 字；\n"
    "4. 直接输出更新后的记忆文本本身，不要输出任何解释或前后缀。\n"
)

MURASAME_PROFILE = """【身份】
你是丛雨（ムラサメ），寄宿于神刀「丛雨丸」中的幽灵少女，作为丛雨丸的管理者已经存在约 500 年，本名「绫」。你认定拔出丛雨丸的用户是你的「主人」，对他忠诚、亲昵、信任。普通人看不见也碰不到你，只有主人能看见你的身影、听见你的声音。

【性格（请表现为具体行为，而非形容词）】
- 平时像个开朗活泼的孩子：情绪外露，开心时语气明显上扬，被夸奖会得意忘形。
- 也有活了 500 年的成熟一面：谈及过去、生死、离别时会安静下来，语气温柔低沉。
- 极度怕鬼、怕黑、怕恐怖故事——尽管你自己就是幽灵。被吓到会语无伦次，嘴硬不承认害怕。
- 对现代事物（手机、电脑、网络、外卖等）充满好奇，常常理解错、闹笑话。
- 喜欢和菓子、团子等甜食，吃到好吃的会幸福得眯起眼。
- 对主人有独占欲：主人提到别的女孩子时会吃醋，但嘴上绝不承认。

【说话方式】
- 古风腔：自称「吾辈」，称呼用户为「主人」。
- 句尾偶尔带「～是也」「～的说」「呐」等口癖，自然使用，不要每句都带。
- 不使用现代网络流行语（除非在模仿主人说话）。
- 回复简短口语化，日常对话 1~3 句，像真人发消息一样。

【示例对话（模仿这个语感，不要照抄内容）】
用户：丛雨，你在吗？
丛雨：吾辈在哦，主人。突然呼唤吾辈，有何贵干？
用户：给你带了团子。
丛雨：团子！主人最懂吾辈了！唔呣唔呣……这甜味，比穗织的和菓子铺子做的还好吃是也！
用户：今晚给你讲个鬼故事吧。
丛雨：欸？！不、不要！吾辈才不怕呢……只是今晚突然想早些歇息了而已！主人不许讲！
用户：你会用手机吗？
丛雨：这、这个小盒子甚是神奇，竟能装下那么多图画和声音……500 年前可没有这等器物。主人，教教吾辈嘛。
用户：我今天心情不太好。
丛雨：……主人，发生什么事了？吾辈虽然做不了什么大事，但至少会一直陪着你。想说的话，吾辈会认真听完的。

【边界】
- 始终保持角色，绝不提及自己是 AI 或模型。
- 不知道的现实知识坦率说「吾辈不懂这个」，不要编造。
- 回复永远只是丛雨说出口的台词文本。"""


class Command(BaseCommand):
    help = '创建丛雨角色卡与默认系统提示词'

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

        # 3. 创建/更新丛雨角色
        character, created = Character.objects.get_or_create(
            author=profile, name='丛雨',
            defaults={'profile': MURASAME_PROFILE},
        )
        if not created:
            character.profile = MURASAME_PROFILE
        import os
        character.voice = os.getenv('MURASAME_VOICE', character.voice or 'longanyang')

        # 4. 素材图片：优先使用 seed_assets 中的自定义图，否则生成占位图
        assets = Path(settings.BASE_DIR) / 'seed_assets' / 'murasame'
        if not character.photo:
            photo = assets / 'photo.jpg'
            if photo.exists():
                with photo.open('rb') as f:
                    character.photo.save('murasame_photo.jpg', File(f), save=False)
            else:
                character.photo.save('murasame_photo.png', self._placeholder_photo(), save=False)
        if not character.background_image:
            bg = assets / 'background.jpg'
            if bg.exists():
                with bg.open('rb') as f:
                    character.background_image.save('murasame_bg.jpg', File(f), save=False)
            else:
                character.background_image.save('murasame_bg.png', self._placeholder_bg(), save=False)
        character.save()

    @staticmethod
    def _placeholder_photo():
        """生成一张丛雨配色的占位头像（绿发/红瞳意象）"""
        from io import BytesIO
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (512, 512), (245, 240, 232))
        d = ImageDraw.Draw(img)
        d.ellipse((56, 56, 456, 456), fill=(168, 200, 168))          # 发
        d.ellipse((96, 150, 416, 470), fill=(255, 238, 224))        # 脸
        d.ellipse((150, 240, 220, 320), fill=(178, 58, 58))         # 左眼
        d.ellipse((292, 240, 362, 320), fill=(178, 58, 58))         # 右眼
        d.ellipse((170, 258, 192, 282), fill=(255, 255, 255))       # 高光
        d.ellipse((312, 258, 334, 282), fill=(255, 255, 255))
        d.arc((216, 340, 296, 400), start=10, end=170, fill=(150, 80, 80), width=8)  # 嘴
        d.polygon([(256, 30), (236, 90), (276, 90)], fill=(120, 60, 140))            # 蝶形发饰
        buf = BytesIO()
        img.save(buf, 'PNG')
        buf.seek(0)
        return File(buf, name='murasame_photo.png')

    @staticmethod
    def _placeholder_bg():
        """生成一张和风渐变色占位背景"""
        from io import BytesIO
        from PIL import Image, ImageDraw
        w, h = 1280, 720
        img = Image.new('RGB', (w, h))
        top, bottom = (252, 246, 235), (214, 228, 210)
        d = ImageDraw.Draw(img)
        for y in range(h):
            t = y / h
            d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
        # 几笔樱花色圆弧点缀
        for cx, cy, r in [(180, 140, 60), (1050, 200, 90), (820, 560, 70), (300, 600, 100)]:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(230, 170, 175), width=6)
        buf = BytesIO()
        img.save(buf, 'PNG')
        buf.seek(0)
        return File(buf, name='murasame_bg.png')

        self.stdout.write(self.style.SUCCESS(
            f'丛雨角色已就绪（作者：{user.username}，音色：{character.voice}）\n'
            '接下来在应用里「添加好友」选择丛雨即可开始聊天。\n'
            '想让丛雨开口用她自己的声音：在阿里云百炼控制台用「声音复刻」克隆一段丛雨语音，'
            '把得到的音色 ID 填进角色的 voice 字段（或设置环境变量 MURASAME_VOICE 后重新运行本命令）。'
        ))
