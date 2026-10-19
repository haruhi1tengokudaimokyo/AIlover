<script setup lang="ts">
/**
 * 无业务面板：surface 底 + 16px 圆角 + card 阴影。
 */
withDefaults(
  defineProps<{
    padded?: boolean
    elevated?: boolean
  }>(),
  {
    padded: true,
    elevated: false,
  },
)
</script>

<template>
  <div
    class="rounded-panel border border-base-content/5 bg-surface shadow-card"
    :class="{ 'p-5 md:p-6': padded, 'shadow-pop': elevated }"
  >
    <slot></slot>
  </div>
</template>
