from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('web', '0009_character_greeting_character_quick_replies_and_more')]
    operations = [
        migrations.AddField(model_name='friend', name='memory_enabled', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='friend', name='memory_revision', field=models.PositiveIntegerField(default=0)),
    ]
