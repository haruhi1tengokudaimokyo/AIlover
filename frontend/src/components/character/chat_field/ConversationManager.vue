<script setup>
import { onMounted, ref } from 'vue'
import api from '@/js/http/api.js'

const props = defineProps(['friendId'])
const emit = defineEmits(['close', 'cleared'])
const memory = ref('')
const enabled = ref(true)
const revision = ref(0)
const ready = ref(false)
const busy = ref(false)
const status = ref('')
const query = ref('')
const results = ref([])
const more = ref(false)
const searched = ref(false)
const memoryMode = ref('legacy')
const legacyRetired = ref(false)
const items = ref([])
const itemMore = ref(false)
const source = ref(null)
const newMemory = ref('')
const newKind = ref('semantic')

function errorText(err) { return err.response?.data?.result || err.response?.data?.detail || '操作失败，请重试' }
async function loadMemory() {
  try {
    const { data } = await api.get('/api/friend/memory/', { params: { friend_id: props.friendId } })
    memory.value = data.memory
    enabled.value = data.enabled
    revision.value = data.revision
    memoryMode.value = data.mode
    legacyRetired.value = data.legacy_retired
    await loadItems()
    ready.value = true
  } catch (err) { status.value = errorText(err) }
}
async function saveMemory(clear = false, restoreLegacy = false) {
  if (busy.value || !ready.value) return
  if (clear && !window.confirm('清空长期记忆并关闭自动记忆？聊天记录仍会保留。')) return
  if (restoreLegacy && !window.confirm('确认你已审核此摘要？其中的信息将重新用于旧版模式的对话。')) return
  busy.value = true
  try {
    const { data } = await api.patch('/api/friend/memory/', {
      friend_id: props.friendId, memory: clear ? '' : memory.value,
      enabled: clear ? false : enabled.value, revision: revision.value,
      clear_all: clear,
      restore_legacy: restoreLegacy,
    })
    memory.value = data.memory
    enabled.value = data.enabled
    revision.value = data.revision
    legacyRetired.value = data.legacy_retired
    await loadItems()
    status.value = clear ? '记忆已清空，自动记忆已关闭' : '记忆已保存'
  } catch (err) { status.value = errorText(err) }
  finally { busy.value = false }
}
async function loadItems(append = false) {
  const { data } = await api.get('/api/friend/memory/items/', { params: {
    friend_id: props.friendId, before: append ? items.value.at(-1)?.id : 0,
  } })
  items.value = append ? [...items.value, ...data.items] : data.items
  itemMore.value = data.has_more
  revision.value = data.revision
}
async function mutateItem(item, deleting = false) {
  if (busy.value) return
  if (deleting && !window.confirm('忘记这条记忆？旧消息和任务不会再次恢复它；聊天记录仍保留。')) return
  busy.value = true
  try {
    const payload = { friend_id: props.friendId, id: item.id, revision: revision.value, text: item.content.text }
    if (deleting) await api.delete('/api/friend/memory/items/', { data: payload })
    else await api.patch('/api/friend/memory/items/', payload)
    source.value = null
    await loadMemory()
    status.value = deleting ? '已忘记这条记忆' : '已人工修正'
  } catch (err) { status.value = errorText(err) }
  finally { busy.value = false }
}
async function addMemory() {
  if (busy.value || !newMemory.value.trim()) return
  busy.value = true
  try {
    await api.post('/api/friend/memory/items/', { friend_id: props.friendId, text: newMemory.value,
      kind: newKind.value, revision: revision.value })
    newMemory.value = ''
    await loadMemory()
    status.value = '已添加人工记忆'
  } catch (err) { status.value = errorText(err) }
  finally { busy.value = false }
}
async function showSource(item) {
  if (busy.value) return
  busy.value = true
  try {
    const { data } = await api.get('/api/friend/memory/source/', { params: { friend_id: props.friendId, id: item.id } })
    source.value = data
  } catch (err) { status.value = errorText(err) }
  finally { busy.value = false }
}
async function search(append = false) {
  if (busy.value || !query.value.trim()) return
  busy.value = true
  try {
    const { data } = await api.get('/api/friend/message/search/', { params: {
      friend_id: props.friendId, q: query.value.trim(), before: append ? results.value.at(-1)?.id : 0,
    } })
    results.value = append ? [...results.value, ...data.messages] : data.messages
    more.value = data.has_more
    searched.value = true
    status.value = ''
  } catch (err) { status.value = errorText(err) }
  finally { busy.value = false }
}
async function exportChat() {
  if (busy.value) return
  busy.value = true
  try {
    const response = await api.get('/api/friend/message/export/', { params: { friend_id: props.friendId }, responseType: 'blob' })
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = `ailover-chat-${props.friendId}.json`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    status.value = '聊天记录已导出，文件包含长期记忆，请妥善保存'
  } catch (err) { status.value = errorText(err) }
  finally { busy.value = false }
}
async function clearHistory() {
  if (busy.value || !window.confirm('清空这个角色的全部聊天记录和长期记忆？此操作无法撤销，建议先导出。')) return
  busy.value = true
  try {
    await api.delete('/api/friend/message/clear/', { data: { friend_id: props.friendId, confirm: 'CLEAR' } })
    results.value = []
    await loadMemory()
    status.value = '聊天和记忆已清空，自动记忆已关闭'
    emit('cleared')
  } catch (err) { status.value = errorText(err) }
  finally { busy.value = false }
}
onMounted(loadMemory)
</script>

<template>
  <section class="absolute inset-0 z-30 bg-base-100 p-4 overflow-y-auto rounded-2xl" aria-label="记忆和聊天管理">
    <div class="flex justify-between items-center mb-3">
      <strong>记忆与聊天记录</strong>
      <button type="button" class="btn btn-sm btn-ghost" @click="emit('close')">返回聊天</button>
    </div>
    <p class="text-xs opacity-70 mb-2">当前模式：{{ memoryMode === 'structured' ? '结构化记忆' : '旧版摘要' }}。关闭记忆后，不自动提取，也不向模型注入已有记忆。</p>
    <label class="flex items-center gap-2 text-sm mb-2">
      <input v-model="enabled" type="checkbox" class="toggle toggle-sm" :disabled="!ready || busy">启用长期记忆
    </label>
    <p class="text-xs opacity-70">旧版摘要保留供查看与编辑；结构化模式只使用下方条目。{{ legacyRetired ? '此摘要已退出自动注入。' : '' }}</p>
    <textarea v-model="memory" maxlength="5000" rows="5" class="textarea w-full" :disabled="!ready || busy" aria-label="长期记忆" placeholder="暂无长期记忆" />
    <div class="flex gap-2 mt-2">
      <button class="btn btn-sm" :disabled="!ready || busy" @click="saveMemory()">保存修改</button>
      <button class="btn btn-sm btn-ghost" :disabled="busy" @click="loadMemory">重新读取</button>
      <button class="btn btn-sm btn-ghost" :disabled="!ready || busy" @click="saveMemory(true)">清空记忆</button>
      <button v-if="memoryMode === 'legacy' && legacyRetired" class="btn btn-sm btn-ghost" :disabled="busy || !memory.trim()" @click="saveMemory(false, true)">使用审核后的摘要</button>
    </div>
    <p v-if="status" role="status" class="text-sm my-3">{{ status }}</p>
    <div class="mt-4 border-t border-base-300 pt-3">
      <strong>逐条记忆</strong>
      <p v-if="!items.length" class="text-xs opacity-60">暂无条目。结构化自动提取目前仅支持明确称呼、限定饮食偏好、约定和待续话题。</p>
      <article v-for="item in items" :key="item.id" class="bg-base-200 rounded p-2 my-2">
        <p class="text-xs opacity-60">{{ item.kind }} · v{{ item.version }} · {{ item.manual ? '人工' : '用户消息' }}</p>
        <textarea v-model="item.content.text" maxlength="500" rows="2" class="textarea w-full" :disabled="busy" aria-label="记忆条目正文" />
        <div class="flex gap-2 mt-1">
          <button class="btn btn-xs" :disabled="busy" @click="mutateItem(item)">保存纠正</button>
          <button class="btn btn-xs" :disabled="busy" @click="showSource(item)">查看来源</button>
          <button class="btn btn-xs btn-ghost" :disabled="busy" @click="mutateItem(item, true)">忘记</button>
        </div>
      </article>
      <button v-if="itemMore" class="btn btn-xs" :disabled="busy" @click="loadItems(true).catch(err => status = errorText(err))">更多记忆</button>
      <form class="mt-3" @submit.prevent="addMemory">
        <select v-model="newKind" class="select select-sm" :disabled="busy"><option value="semantic">事实/偏好</option><option value="episodic">事件/约定</option><option value="state">待续状态</option></select>
        <textarea v-model="newMemory" class="textarea w-full" maxlength="500" rows="2" placeholder="例如：叫我小林 / 我现在不喝咖啡了。已识别的事实会更新原条目。" :disabled="busy || !ready" aria-label="新增记忆正文" />
        <button class="btn btn-sm" :disabled="busy || !ready || !newMemory.trim()">添加记忆</button>
      </form>
      <aside v-if="source" class="text-sm p-2 my-2 border rounded">
        <p class="whitespace-pre-wrap break-words">{{ source.source ? `消息 #${source.source.id}：${source.source.user_message}` : '人工添加或来源消息已不存在' }}</p>
        <p v-for="change in source.changes" :key="`${change.version}-${change.action}`" class="text-xs">v{{ change.version }} · {{ change.action }} · {{ change.actor }}</p>
      </aside>
    </div>
    <form class="flex gap-2 mt-5" @submit.prevent="search()">
      <input v-model="query" maxlength="200" class="input input-sm flex-1 min-w-0" placeholder="搜索聊天关键词" aria-label="搜索聊天关键词">
      <button class="btn btn-sm" :disabled="busy">搜索</button>
    </form>
    <p v-if="searched && !results.length" class="text-sm opacity-60 my-3">没有找到匹配的聊天</p>
    <article v-for="row in results" :key="row.id" class="bg-base-200 rounded p-3 my-2 text-sm">
      <time class="text-xs opacity-60">{{ new Date(row.create_time).toLocaleString() }}</time>
      <p class="whitespace-pre-wrap break-words"><b>你：</b>{{ row.user_message }}</p>
      <p class="whitespace-pre-wrap break-words"><b>角色：</b>{{ row.output }}</p>
    </article>
    <button v-if="more" class="btn btn-sm" :disabled="busy" @click="search(true)">更多结果</button>
    <div class="flex gap-2 mt-5 border-t border-base-300 pt-3">
      <button class="btn btn-sm" :disabled="busy" @click="exportChat">导出聊天</button>
      <button class="btn btn-sm btn-outline btn-error" :disabled="busy" @click="clearHistory">清空聊天与记忆</button>
    </div>
  </section>
</template>
