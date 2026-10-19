<script setup lang="ts">
/**
 * 无业务骨架屏：variant 决定形状，count 决定重复次数。
 */
withDefaults(
  defineProps<{
    variant?: 'text' | 'card' | 'avatar' | 'image'
    count?: number
  }>(),
  {
    variant: 'text',
    count: 1,
  },
)
</script>

<template>
  <div aria-hidden="true" class="contents">
    <template v-for="i in count" :key="i">
      <div v-if="variant === 'text'" class="skeleton h-4 w-full rounded"></div>
      <div v-else-if="variant === 'avatar'" class="skeleton size-10 shrink-0 rounded-full"></div>
      <div v-else-if="variant === 'image'" class="skeleton w-full aspect-[4/3] rounded-box"></div>
      <div v-else class="skeleton w-full aspect-[3/4] rounded-box"></div>
    </template>
  </div>
</template>
