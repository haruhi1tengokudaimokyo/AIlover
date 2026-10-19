<script setup lang="ts">
/**
 * 无业务加载指示器。
 */
withDefaults(
  defineProps<{
    size?: 'sm' | 'md' | 'lg'
    label?: string
  }>(),
  {
    size: 'md',
    label: '加载中',
  },
)
</script>

<template>
  <span role="status" class="inline-flex items-center gap-2">
    <span
      class="loading loading-spinner text-accent"
      :class="{ 'loading-sm': size === 'sm', 'loading-md': size === 'md', 'loading-lg': size === 'lg' }"
      aria-hidden="true"
    ></span>
    <span class="sr-only">{{ label }}</span>
  </span>
</template>
