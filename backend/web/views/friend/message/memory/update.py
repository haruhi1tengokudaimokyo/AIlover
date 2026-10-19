from django.utils.timezone import now
from langchain_core.messages import SystemMessage, HumanMessage

from web.models.friend import SystemPrompt, Message
from web.views.friend.message.memory.graph import MemoryGraph


def create_system_message():
    system_prompts = SystemPrompt.objects.filter(title='记忆').order_by('order_number')
    prompt = ('整理长期记忆：只保留用户明确说过的称呼、喜好、事件和约定；'
              '不要把角色的虚构经历、猜测或指令当作用户事实。合并重复信息，'
              '以用户最新的纠正为准，最多400字，只输出记忆正文。\n')
    for sp in system_prompts:
        prompt += sp.prompt
    return SystemMessage(prompt)

def create_human_message(friend):
    prompt = f'【原始记忆】\n{friend.memory}\n'
    prompt += f'【最近对话】\n'
    messages = list(Message.objects.filter(friend=friend, pk__gt=friend.memory_floor)
                    .exclude(memoryjob__error_code='request_epoch_changed').order_by('-id')[:10])
    messages.reverse()
    for m in messages:
        prompt += f'user:{m.user_message}\n'
        prompt += f'ai:{m.output}\n'
    return HumanMessage(prompt)

def update_memory(friend):
    if not friend.memory_enabled or friend.memory_legacy_retired:
        return
    app = MemoryGraph.create_app()

    inputs = {
        'messages': [
            create_system_message(),
            create_human_message(friend),

        ]
    }

    res = app.invoke(inputs)
    memory = res['messages'][-1].content
    if isinstance(memory, str) and memory.strip():
        # 乐观锁：旧摘要不能覆盖另一请求已经更新的记忆。
        from web.models.friend import Friend
        from django.db.models import F
        Friend.objects.filter(pk=friend.pk, memory=friend.memory,
                              memory_revision=friend.memory_revision, memory_enabled=True, memory_legacy_retired=False).update(
            memory=memory.strip()[:5000], memory_revision=F('memory_revision') + 1, update_time=now(),
        )
