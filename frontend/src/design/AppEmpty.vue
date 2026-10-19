<script setup lang="ts">
/**
 * 无业务空状态：插画槽 + 标题 + 描述 + 动作槽。
 */
withDefaults(
  defineProps<{
    title?: string
    description?: string
  }>(),
  {
    title: '这里还是空的',
    description: '',
  },
)
</script>

<template>
  <div class="flex flex-col items-center justify-center text-center py-14 px-6 animate-fade-in">
    <div class="mb-4 text-text-dim">
      <slot name="icon">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          class="size-14"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M8.5 10h.01M15.5 10h.01" />
          <path d="M8.8 15.2c.8-.8 2-1.2 3.2-1.2s2.4.4 3.2 1.2" />
        </svg>
      </slot>
    </div>
    <p class="font-bold text-lg">{{ title }}</p>
    <p v-if="description" class="text-sm text-text-dim mt-2 max-w-xs">{{ description }}</p>
    <div v-if="$slots.action" class="mt-5">
      <slot name="action"></slot>
    </div>
  </div>
</template>
