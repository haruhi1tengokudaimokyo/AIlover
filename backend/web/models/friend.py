from django.db import models
from django.utils.timezone import now, localtime

from web.models.character import Character
from web.models.user import UserProfile

class Friend(models.Model):
    me = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    character = models.ForeignKey(Character, on_delete=models.CASCADE)
    memory = models.TextField(default="",max_length=5000, blank=True, null=True)
    memory_enabled = models.BooleanField(default=True)
    memory_revision = models.PositiveIntegerField(default=0)
    memory_epoch = models.PositiveIntegerField(default=0)
    memory_floor = models.PositiveBigIntegerField(default=0)
    memory_legacy_retired = models.BooleanField(default=False)
    create_time = models.DateTimeField(default=now)
    update_time = models.DateTimeField(default=now)

    def __str__(self):
        return f"{self.character.name} - {self.me.user.username} - {localtime(self.create_time).strftime('%Y-%m-%d %H:%M:%S')}"

class Message(models.Model):
    friend = models.ForeignKey(Friend, on_delete=models.CASCADE)
    user_message = models.TextField(max_length=2000)
    input = models.TextField(max_length=20000)
    output = models.TextField(max_length=5000)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    create_time = models.DateTimeField(default=now)

    def __str__(self):
        return f"{self.friend.character.name} - {self.friend.me.user.username} - {self.user_message[:50]} - {localtime(self.create_time).strftime('%Y-%m-%d %H:%M:%S')}"

class SystemPrompt(models.Model):
    title = models.CharField(max_length=100)
    order_number = models.IntegerField(default=0)
    prompt = models.TextField(max_length=10000)
    create_time = models.DateTimeField(default=now)
    update_time = models.DateTimeField(default=now)

    def __str__(self):
        return f"{self.title} - {self.order_number} - {self.prompt[:50]} - {localtime(self.create_time).strftime('%Y-%m-%d %H:%M:%S')}"


class MemoryItem(models.Model):
    # Ownership is normalized through Friend -> UserProfile/User and Character.
    friend = models.ForeignKey(Friend, on_delete=models.CASCADE, related_name='memory_items')
    kind = models.CharField(max_length=16, choices=[(v, v) for v in ('semantic', 'episodic', 'state', 'relationship')])
    key = models.CharField(max_length=160)
    content = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default='active', choices=[(v, v) for v in ('active', 'deleted')])
    version = models.PositiveIntegerField(default=1)
    source_message = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True)
    evidence_id = models.PositiveBigIntegerField(default=0)
    blocked_through_id = models.PositiveBigIntegerField(default=0)
    manual = models.BooleanField(default=False)
    confidence = models.FloatField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    create_time = models.DateTimeField(default=now)
    update_time = models.DateTimeField(default=now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['friend', 'key'], name='unique_friend_memory_key')]
        indexes = [models.Index(fields=['friend', 'status', 'kind'], name='memory_friend_status_kind')]


class MemoryChange(models.Model):
    item = models.ForeignKey(MemoryItem, on_delete=models.CASCADE, related_name='changes')
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=24)
    content = models.JSONField(default=dict)
    source_message = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True)
    actor = models.CharField(max_length=16, default='user_message')
    create_time = models.DateTimeField(default=now)


class MemoryJob(models.Model):
    friend = models.ForeignKey(Friend, on_delete=models.CASCADE, related_name='memory_jobs')
    message = models.OneToOneField(Message, on_delete=models.CASCADE)
    epoch = models.PositiveIntegerField()
    status = models.CharField(max_length=16, default='pending', choices=[(v, v) for v in ('pending', 'running', 'done', 'cancelled', 'failed')])
    attempts = models.PositiveIntegerField(default=0)
    lease_token = models.CharField(max_length=32, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    retry_at = models.DateTimeField(default=now)
    error_code = models.CharField(max_length=32, blank=True)
    create_time = models.DateTimeField(default=now)
    update_time = models.DateTimeField(default=now)

    class Meta:
        indexes = [models.Index(fields=['status', 'retry_at'], name='memory_job_ready')]
