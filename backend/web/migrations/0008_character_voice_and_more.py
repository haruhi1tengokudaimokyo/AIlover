# Generated for AIlover desktop & character-voice upgrade
from django.db import migrations, models
import web.models.character


class Migration(migrations.Migration):

    dependencies = [
        ('web', '0007_systemprompt'),
    ]

    operations = [
        # SystemPrompt 字段名与代码保持一致（prompts -> prompt）
        migrations.RenameField(
            model_name='systemprompt',
            old_name='prompts',
            new_name='prompt',
        ),
        # 角色图片改为可选，方便种子脚本/无图角色
        migrations.AlterField(
            model_name='character',
            name='photo',
            field=models.ImageField(blank=True, default='', upload_to=web.models.character.photo_upload_to),
        ),
        migrations.AlterField(
            model_name='character',
            name='background_image',
            field=models.ImageField(blank=True, default='', upload_to=web.models.character.background_image_upload_to),
        ),
        # 每个角色独立的 TTS 音色
        migrations.AddField(
            model_name='character',
            name='voice',
            field=models.CharField(default='longanyang', max_length=100),
        ),
        # 放宽消息长度，避免长回复被截断
        migrations.AlterField(
            model_name='message',
            name='user_message',
            field=models.TextField(max_length=2000),
        ),
        migrations.AlterField(
            model_name='message',
            name='input',
            field=models.TextField(max_length=20000),
        ),
        migrations.AlterField(
            model_name='message',
            name='output',
            field=models.TextField(max_length=5000),
        ),
    ]
