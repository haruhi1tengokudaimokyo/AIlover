import uuid

from django.db import models
from django.utils.timezone import now, localtime

from web.models.user import UserProfile

def photo_upload_to(instance, filename):
    ext = filename.split('.')[-1]
    filename = f'{uuid.uuid4().hex[:10]}.{ext}'
    return f'character/photos/{instance.author.user_id}_{filename}'

def background_image_upload_to(instance, filename):
    ext = filename.split('.')[-1]
    filename = f'{uuid.uuid4().hex[:10]}.{ext}'
    return f'character/background_images/{instance.author.user_id}_{filename}'

class Character(models.Model):
    author = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    photo = models.ImageField(upload_to=photo_upload_to, blank=True, default='')
    profile = models.TextField(max_length=100000)
    background_image = models.ImageField(upload_to=background_image_upload_to, blank=True, default='')
    # 阿里云百炼 CosyVoice 音色 ID（可用「声音复刻」克隆角色音色后填入）
    voice = models.CharField(max_length=100, default='longanyang')
    # 角色标识（用于关联台词库 / 素材目录，如 hika、ayame；空表示无附加资源）
    slug = models.CharField(max_length=50, blank=True, default='')
    # 开场白：用户首次添加好友且没有聊天记录时，前端展示为角色的第一条消息
    greeting = models.TextField(max_length=2000, blank=True, default='')
    # 快捷话题建议（JSON 数组字符串，如 ["话题1","话题2"]），前端渲染为可点击的话题气泡
    quick_replies = models.TextField(max_length=2000, blank=True, default='')
    create_time = models.DateTimeField(default=now)
    update_time = models.DateTimeField(default=now)

    def __str__(self):
        return f"{self.author.user.username} - {self.name} - {localtime(self.create_time).strftime('%Y-%m-%d %H:%M:%S')}"