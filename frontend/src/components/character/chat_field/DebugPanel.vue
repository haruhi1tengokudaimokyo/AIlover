<script setup>
import { ref, watch, onUnmounted } from 'vue'
import api from '@/js/http/api.js'
const props = defineProps(['friendId', 'generationId', 'trace'])
const snapshot = ref(null)
const status = ref('')
const loading = ref(false)
let controller = null
let version = 0
watch(() => props.generationId, () => {
  ++version
  controller?.abort()
  snapshot.value = null
  status.value = ''
  loading.value = false
})
onUnmounted(() => { ++version; controller?.abort() })
async function inspectEvidence() {
  controller?.abort()
  controller = new AbortController()
  const current = ++version
  loading.value = true
  try {
    const { data } = await api.get('/api/friend/message/chat/debug/', {
      params: { friend_id: props.friendId, generation_id: props.generationId }, signal: controller.signal,
    })
    if (version === current) { snapshot.value = data; status.value = data.notice }
  } catch (err) {
    if (version === current && !controller.signal.aborted) status.value = '诊断不可用或已过期，请检查开发开关。'
  } finally { if (version === current) loading.value = false }
}
</script>
<template>
  <details class="absolute top-22 left-2 right-2 bg-black/90 text-white p-2 text-xs z-20 max-h-80 overflow-auto">
    <summary>本轮检索、记忆与延迟诊断（开发模式）</summary>
    <pre class="whitespace-pre-wrap">{{ JSON.stringify(trace, null, 2) }}</pre>
    <button class="btn btn-xs" :disabled="loading || !generationId" @click="inspectEvidence">{{ loading ? '读取中' : '查看注入证据与来源' }}</button>
    <p v-if="status" class="my-2">{{ status }}</p>
    <template v-if="snapshot">
      <section v-for="channel in ['lore', 'style', 'memory']" :key="channel" class="my-2 border-t border-white/20">
        <b>{{ channel }}</b>
        <p v-if="!snapshot.evidence[channel].length">没有当前可查看条目</p>
        <article v-for="row in snapshot.evidence[channel]" :key="row.id" class="my-2">
          <p>{{ row.id }} · {{ row.source_file || row.kind }} · {{ row.source_location || `v${row.version}` }}</p>
          <p class="whitespace-pre-wrap break-words">{{ row.text }}</p>
          <p v-for="context in row.context || []" :key="context.id" class="opacity-70">{{ context.speaker }}：{{ context.text }}</p>
          <p v-if="row.source" class="opacity-70">用户消息 #{{ row.source.id }}：{{ row.source.user_message }}</p>
        </article>
      </section>
    </template>
  </details>
</template>
