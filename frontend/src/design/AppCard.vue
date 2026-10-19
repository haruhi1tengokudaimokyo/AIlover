<script setup lang="ts">
/**
 * 无业务卡片：12px 圆角（--radius-box），hoverable 时上浮 + 阴影加深。
 */
withDefaults(
  defineProps<{
    hoverable?: boolean
    padded?: boolean
  }>(),
  {
    hoverable: false,
    padded: false,
  },
)
</script>

<template>
  <div
    class="rounded-box bg-surface shadow-card transition-all duration-250 ease-soft"
    :class="{
      'hover:-translate-y-1 hover:shadow-pop': hoverable,
      'p-4': padded,
    }"
  >
    <slot></slot>
  </div>
</template>
