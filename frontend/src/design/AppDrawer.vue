<script setup lang="ts">
/**
 * 无业务抽屉：v-model:open 控制，支持左/右/下三侧滑出。
 * 点击遮罩或 Esc 关闭；尊重 prefers-reduced-motion（全局已降级）。
 */
import { onBeforeUnmount, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    side?: 'left' | 'right' | 'bottom'
    title?: string
  }>(),
  {
    side: 'right',
    title: '',
  },
)

const emit = defineEmits<{ 'update:open': [value: boolean] }>()

function close() {
  emit('update:open', false)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) close()
}

watch(
  () => props.open,
  open => {
    if (typeof document === 'undefined') return
    if (open) {
      document.addEventListener('keydown', onKeydown)
      document.body.style.overflow = 'hidden'
    } else {
      document.removeEventListener('keydown', onKeydown)
      document.body.style.overflow = ''
    }
  },
)

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50" role="dialog" aria-modal="true" :aria-label="title || '抽屉'">
      <div class="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in" @click="close"></div>
      <aside
        class="absolute flex flex-col bg-surface shadow-stage transition-transform duration-250 ease-soft"
        :class="{
          'inset-y-0 left-0 w-80 max-w-[85vw] rounded-r-panel': side === 'left',
          'inset-y-0 right-0 w-80 max-w-[85vw] rounded-l-panel': side === 'right',
          'inset-x-0 bottom-0 max-h-[80vh] rounded-t-panel': side === 'bottom',
        }"
      >
        <header v-if="title" class="flex items-center justify-between px-5 py-4 border-b border-base-content/8">
          <h2 class="font-bold text-lg">{{ title }}</h2>
          <button class="btn btn-ghost btn-sm btn-circle" aria-label="关闭" @click="close">✕</button>
        </header>
        <div class="flex-1 overflow-y-auto">
          <slot></slot>
        </div>
      </aside>
    </div>
  </Teleport>
</template>
