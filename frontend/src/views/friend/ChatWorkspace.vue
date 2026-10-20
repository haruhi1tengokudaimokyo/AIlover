<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import api from '@/js/http/api.js'
import CharacterStage from '@/stage/CharacterStage.vue'
import type { StageCharacter } from '@/stage/renderer'
import type { CharacterState } from '@/stage/characterState'
import ChatHistory from '@/components/character/chat_field/chat_history/ChatHistory.vue'
import InputField from '@/components/character/chat_field/input_field/InputField.vue'
import ConversationManager from '@/components/character/chat_field/ConversationManager.vue'

interface Message { id: string; role: string; content: string; status?: string }
const route = useRoute()
const friend = ref<{ id: number; character: StageCharacter } | null>(null)
const error = ref('')
const loading = ref(true)
const immersive = ref(false)
const showHistory = ref(false)
const managing = ref(false)
const managerDialog = ref<HTMLDialogElement | null>(null)
const history = ref<Message[]>([])
const historyVersion = ref(0)
const state = ref<CharacterState>('idle')
const input = ref<InstanceType<typeof InputField> | null>(null)
const historyView = ref<InstanceType<typeof ChatHistory> | null>(null)
const subtitle = computed(() => [...history.value].reverse().find(m => m.role === 'ai')?.content || friend.value?.character.greeting || '故事，就从这一刻开始。')
let request: AbortController | null = null
let version = 0
const viewportStyle = ref<Record<string, string>>({})
function resizeViewport() {
  const viewport = window.visualViewport
  viewportStyle.value = { height: `${viewport?.height || window.innerHeight}px`, top: `${viewport?.offsetTop || 0}px` }
}
resizeViewport()
window.addEventListener('resize', resizeViewport)
window.visualViewport?.addEventListener('resize', resizeViewport)
window.visualViewport?.addEventListener('scroll', resizeViewport)
async function loadFriend() {
  const current = ++version
  input.value?.close()
  request?.abort()
  request = new AbortController()
  friend.value = null
  history.value = []
  state.value = 'idle'
  managing.value = false
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/api/friend/get_single/', { signal: request.signal, params: { friend_id: route.params.friendId } })
    if (current !== version) return
    if (data.result !== 'success') throw new Error(data.result)
    friend.value = data.friend
  } catch (err: unknown) {
    if (current === version) error.value = (err as { response?: { data?: { result?: string } } }).response?.data?.result || '无法打开这段对话，请检查登录状态或网络连接。'
  } finally { if (current === version) loading.value = false }
}
watch(() => route.params.friendId, loadFriend, { immediate: true })
watch([immersive, showHistory], async () => { await nextTick(); historyView.value?.scrollToBottom() })
function append(message: Message) {
  history.value.push(message)
  historyView.value?.scrollToBottom(message.role === 'user')
}
function delta(text: string) {
  const message = history.value[history.value.length - 1]
  if (message?.role === 'ai') message.content += text
  historyView.value?.scrollToBottom()
}
function finish(status: string) { const message = history.value[history.value.length - 1]; if (message?.role === 'ai') message.status = status }
function clear() { history.value = []; historyVersion.value++ }
async function openManager() { input.value?.close(); managing.value = true; await nextTick(); managerDialog.value?.showModal() }
onBeforeUnmount(() => {
  ++version
  request?.abort()
  input.value?.close()
  window.removeEventListener('resize', resizeViewport)
  window.visualViewport?.removeEventListener('resize', resizeViewport)
  window.visualViewport?.removeEventListener('scroll', resizeViewport)
})
</script>

<template>
  <div class="chat-workspace" :class="{ immersive, 'history-open': showHistory }" :style="viewportStyle">
    <div v-if="loading || error" class="workspace-placeholder" role="status">
      <p>{{ loading ? '正在打开你们的故事…' : error }}</p>
      <button v-if="error" class="btn btn-sm mt-4" @click="loadFriend">重新加载</button>
      <RouterLink class="btn btn-sm btn-ghost mt-4" to="/friend/">返回好友</RouterLink>
    </div>
    <template v-else-if="friend">
      <header class="workspace-toolbar">
        <RouterLink to="/friend/" class="workspace-back" aria-label="返回好友">← <span>相伴</span></RouterLink>
        <span class="workspace-title">{{ friend.character.name }} <small>与你的故事</small></span>
        <button class="workspace-action" @click="openManager">记忆与记录</button>
        <button class="workspace-action" :aria-pressed="immersive" @click="immersive = !immersive">{{ immersive ? '退出沉浸' : '沉浸模式' }}</button>
      </header>
      <CharacterStage :character="friend.character" :state="state" :immersive="immersive" />
      <section class="conversation-panel" aria-label="对话面板">
        <div class="panel-heading"><div><span>CONVERSATION</span><h2>把这一刻，留给彼此。</h2></div><button class="workspace-action mobile-history" :aria-expanded="showHistory" @click="showHistory = !showHistory">{{ showHistory ? '收起记录' : '聊天记录' }}</button></div>
        <ChatHistory ref="historyView" :key="`${friend.id}-${historyVersion}`" :history="history" :friendId="friend.id" :character="friend.character" @pushFrontMessage="history.unshift($event)" @pushBackMessage="append" @quickReply="input?.sendQuick($event)" />
        <div class="vn-subtitle" tabindex="0"><span>{{ friend.character.name }}</span><p>{{ subtitle }}</p></div>
        <div class="workspace-composer">
          <InputField ref="input" :key="friend.id" :friendId="friend.id" @pushBackMessage="append" @addToLastMessage="delta" @finishMessage="finish" @state="state = $event" />
          <p class="composer-footnote">此刻的心情，都可以慢慢说。</p>
        </div>
      </section>
      <dialog v-if="managing" ref="managerDialog" class="manager-backdrop" aria-label="记忆与聊天管理" @close="managing = false" @click.self="managing = false">
        <div class="manager-container"><ConversationManager :friendId="friend.id" @close="managing = false" @cleared="clear" /></div>
      </dialog>
    </template>
  </div>
</template>

<style scoped>
.chat-workspace{position:fixed;inset:0 0 0 80px;display:grid;grid-template-columns:minmax(0,1fr) clamp(350px,31vw,470px);grid-template-rows:64px minmax(0,1fr);background:var(--color-base);z-index:35;min-width:0}
.workspace-toolbar{grid-column:1/-1;display:flex;align-items:center;gap:12px;padding:env(safe-area-inset-top) 24px 0;border-bottom:1px solid #a89fb820;background:var(--color-surface)}.workspace-back{font-size:20px;display:flex;gap:12px;align-items:center}.workspace-back span{font-size:12px;color:var(--color-text-dim)}.workspace-title{flex:1;font-size:14px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.workspace-title small{font-size:11px;color:var(--color-text-dim);margin-left:12px}.workspace-action{padding:8px 12px;font-size:11px;border:1px solid #a89fb830;border-radius:8px;white-space:nowrap}.workspace-action:hover{background:var(--color-surface-2)}
.conversation-panel{display:flex;flex-direction:column;min-width:0;min-height:0;background:var(--color-surface);border-left:1px solid #a89fb820}.panel-heading{display:flex;justify-content:space-between;align-items:center;padding:24px 22px 15px;border-bottom:1px solid #a89fb815}.panel-heading span{font-size:9px;letter-spacing:.22em;color:var(--color-accent)}.panel-heading h2{font-family:var(--font-display);font-size:17px;margin-top:6px}.workspace-composer{padding:14px 20px max(10px,env(safe-area-inset-bottom));border-top:1px solid #a89fb820;position:relative;flex-shrink:0}.composer-footnote{text-align:center;font-size:9px;color:var(--color-text-dim);margin-top:10px;letter-spacing:.1em}.mobile-history,.vn-subtitle{display:none}.workspace-placeholder{grid-column:1/-1;grid-row:1/-1;align-self:center;text-align:center;padding:24px}.manager-backdrop{position:fixed;inset:0;width:100%;height:100%;max-width:none;max-height:none;background:transparent;color:var(--color-text);z-index:50;align-items:center;justify-content:center;padding:20px}.manager-backdrop[open]{display:flex}.manager-backdrop::backdrop{background:#100c1cb3}.manager-container :deep(.flex){flex-wrap:wrap}.manager-container{position:relative;width:min(680px,100%);height:90%;box-shadow:var(--shadow-stage)}
.immersive{left:0;z-index:60;grid-template-columns:1fr}.immersive .character-stage{grid-column:1;grid-row:2}.immersive .conversation-panel{position:absolute;bottom:20px;left:50%;transform:translateX(-50%);width:min(880px,calc(100% - 48px));max-height:65%;background:#1b1629ed;color:#f2ede7;border:1px solid #ffffff25;border-radius:14px;--color-surface:#241c32;--color-surface-2:#30263f;--color-text-dim:#c4b9cf;--color-base:#17111f}.immersive .panel-heading{padding:12px 20px}.immersive .panel-heading h2{display:none}.immersive .mobile-history{display:block}.immersive .conversation-history{display:none}.immersive.history-open .conversation-history{display:block;flex:initial;height:240px}.immersive .vn-subtitle{display:block;padding:14px 24px 0}.vn-subtitle span{color:#edc1d9;font-size:14px;font-weight:700}.vn-subtitle p{font-family:var(--font-display);font-size:17px;line-height:1.9;margin-top:8px;max-height:150px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}.immersive.history-open .vn-subtitle{display:none}.immersive .workspace-composer{border-top:0}
@media(max-width:1023px){.chat-workspace{left:0;z-index:50;grid-template-columns:minmax(0,1fr) 350px}.workspace-toolbar{padding:env(safe-area-inset-top) 14px 0}.workspace-back span{display:none}}
@media(max-width:767px){.chat-workspace{grid-template-columns:1fr;grid-template-rows:calc(54px + env(safe-area-inset-top)) minmax(145px,32%) minmax(0,1fr)}.workspace-toolbar{gap:7px;padding:env(safe-area-inset-top) 10px 0}.workspace-action{font-size:10px;padding:7px}.workspace-title small{display:none}.workspace-title{font-size:12px}.conversation-panel{border-left:0}.panel-heading{padding:9px 14px}.panel-heading h2{font-size:13px;margin-top:2px}.panel-heading span{font-size:8px}.workspace-composer{padding:10px 12px max(8px,env(safe-area-inset-bottom))}.composer-footnote{display:none}.manager-backdrop{padding:8px}.manager-container{height:96%}.immersive{grid-template-rows:calc(54px + env(safe-area-inset-top)) minmax(0,1fr)}.immersive .conversation-panel{bottom:max(10px,env(safe-area-inset-bottom));width:calc(100% - 20px);max-height:65%}.immersive .vn-subtitle{padding:12px 16px 0}.vn-subtitle p{font-size:15px;max-height:120px}.immersive.history-open .conversation-history{height:190px}.history-open:not(.immersive){grid-template-rows:calc(54px + env(safe-area-inset-top)) 100px minmax(0,1fr)}.mobile-history{display:block}}
</style>
