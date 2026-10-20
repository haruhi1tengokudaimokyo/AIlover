<script setup>
import Message from './message/Message.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import api from '@/js/http/api.js'
const props = defineProps(['history', 'friendId', 'character'])
const emit = defineEmits(['pushFrontMessage', 'pushBackMessage', 'quickReply'])
const scrollRef = ref(null)
const loading = ref(false)
const more = ref(true)
const error = ref('')
const atBottom = ref(true)
let before = 0
let disposed = false
const controller = new AbortController()
const showQuickReplies = computed(() => !props.history.some(m => m.role === 'user'))
function trackScroll() {
  const el = scrollRef.value
  if (el?.clientHeight) atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
async function loadMore() {
  if (loading.value || !more.value || disposed) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/api/friend/message/get_history/', { signal: controller.signal, params: { friend_id: props.friendId, last_message_id: before } })
    if (disposed) return
    if (data.result !== 'success') throw new Error(data.result)
    const el = scrollRef.value
    const height = el.scrollHeight
    const top = el.scrollTop
    const first = before === 0
    more.value = data.messages.length > 0
    for (const m of data.messages) {
      emit('pushFrontMessage', { role: 'ai', content: m.output, id: `ai-${m.id}` })
      emit('pushFrontMessage', { role: 'user', content: m.user_message, id: `user-${m.id}` })
      before = m.id
    }
    if (first && !props.history.length && props.character?.greeting) emit('pushBackMessage', { role: 'ai', content: props.character.greeting, id: 'greeting' })
    await nextTick()
    if (disposed) return
    el.scrollTop = first ? el.scrollHeight : top + el.scrollHeight - height
    trackScroll()
  } catch (err) { if (!disposed) error.value = '历史记录加载失败，请重试' }
  finally { if (!disposed) loading.value = false }
}
async function scrollToBottom(force = false) {
  if (!force && !atBottom.value) return
  await nextTick()
  if (!disposed && scrollRef.value?.clientHeight) { scrollRef.value.scrollTop = scrollRef.value.scrollHeight; atBottom.value = true }
}
onMounted(loadMore)
onBeforeUnmount(() => { disposed = true; controller.abort() })
defineExpose({ scrollToBottom })
</script>
<template>
  <div class="conversation-history">
    <div ref="scrollRef" class="message-scroll" @scroll.passive="trackScroll">
      <button v-if="more" type="button" class="history-more" :disabled="loading" @click="loadMore">{{ loading ? '正在读取回忆…' : '加载更早的聊天' }}</button>
      <p v-if="error" class="text-error text-xs text-center" role="alert">{{ error }} <button class="underline" @click="loadMore">重试</button></p>
      <div class="conversation-intro"><span>OUR STORY</span><p>每一次对话，都值得被记住。</p></div>
      <Message v-for="message in history" :key="message.id" :message="message" :character="character" />
      <div v-if="showQuickReplies && character?.quick_replies?.length" class="quick-replies">
        <button v-for="text in character.quick_replies" :key="text" @click="emit('quickReply', text)">{{ text }} ↗</button>
      </div>
    </div>
    <button v-if="!atBottom" class="jump-latest" @click="scrollToBottom(true)">↓ 回到最新消息</button>
  </div>
</template>
<style scoped>
.conversation-history{position:relative;flex:1;min-height:0}.message-scroll{height:100%;overflow:auto;padding:12px 20px 24px;overscroll-behavior:contain;overflow-anchor:none}.history-more{display:block;margin:0 auto;padding:8px;font-size:11px;color:var(--color-text-dim)}.conversation-intro{text-align:center;padding:22px 0;color:var(--color-text-dim);font-size:11px}.conversation-intro span{letter-spacing:.25em;font-size:9px}.conversation-intro p{margin-top:8px}.quick-replies{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}.quick-replies button{border:1px solid color-mix(in srgb,var(--color-accent) 25%,transparent);border-radius:8px;padding:8px 10px;font-size:12px;text-align:left}.jump-latest{position:absolute;bottom:12px;left:50%;transform:translateX(-50%);white-space:nowrap;padding:7px 14px;border-radius:20px;background:var(--color-accent);color:var(--color-base);font-size:12px;box-shadow:var(--shadow-card)}
</style>
