<script setup lang="ts">
/**
 * 无业务基础按钮：variant × size，支持 loading 态。
 * 设计契约：按钮圆角 10px（--radius-field），hover/focus 态完整。
 */
const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'neutral' | 'ghost' | 'outline'
    size?: 'sm' | 'md' | 'lg'
    type?: 'button' | 'submit' | 'reset'
    loading?: boolean
    disabled?: boolean
    block?: boolean
  }>(),
  {
    variant: 'primary',
    size: 'md',
    type: 'button',
    loading: false,
    disabled: false,
    block: false,
  },
)

const emit = defineEmits<{ click: [event: MouseEvent] }>()

function onClick(event: MouseEvent) {
  if (props.loading || props.disabled) return
  emit('click', event)
}
</script>

<template>
  <button
    :type="type"
    class="btn transition-all duration-150 ease-soft"
    :class="[
      {
        'btn-primary': variant === 'primary',
        'btn-secondary': variant === 'secondary',
        'btn-neutral': variant === 'neutral',
        'btn-ghost': variant === 'ghost',
        'btn-outline': variant === 'outline',
        'btn-sm': size === 'sm',
        'btn-lg': size === 'lg',
        'w-full': block,
      },
    ]"
    :disabled="disabled || loading"
    :aria-busy="loading"
    @click="onClick"
  >
    <span v-if="loading" class="loading loading-spinner loading-xs" aria-hidden="true"></span>
    <slot></slot>
  </button>
</template>
