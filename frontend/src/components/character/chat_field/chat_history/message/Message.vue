<script setup>
defineProps(['message', 'character'])
</script>
<template>
  <article v-if="message.content || message.status" class="message" :class="{ 'message-user': message.role !== 'ai' }">
    <span class="message-author">{{ message.role === 'ai' ? character.name : '你' }}</span>
    <div class="message-body">{{ message.content }}<span v-if="message.status === 'pending'" class="stream-cursor" aria-label="正在回复">▍</span></div>
    <small v-if="message.status === 'failed'" class="text-error">回复未完成，未保存；可在输入区重试</small>
    <small v-if="message.status === 'stopped'">已停止</small>
  </article>
</template>
<style scoped>
.message{margin:0 0 23px;content-visibility:auto;contain-intrinsic-size:auto 90px}.message-author{font-size:10px;color:var(--color-text-dim);display:block;margin-bottom:8px;letter-spacing:.06em}.message-body{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.85;padding:12px 15px;background:var(--color-surface-2);border-radius:3px 14px 14px 14px}.message-user{margin-left:24px}.message-user .message-author{text-align:right}.message-user .message-body{background:color-mix(in srgb,var(--color-accent) 15%,var(--color-surface));border-radius:14px 3px 14px 14px}.message small{font-size:10px;opacity:.7}.stream-cursor{color:var(--color-accent);animation:blink 1s steps(2) infinite}@keyframes blink{to{opacity:0}}
</style>
