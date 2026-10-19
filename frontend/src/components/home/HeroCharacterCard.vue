<script setup lang="js">
import ChatField from '@/components/character/chat_field/ChatField.vue'
import AppButton from '@/design/AppButton.vue'
import { useOpenChat } from '@/components/home/useOpenChat.js'
import { avatarFallback } from '@/js/utils/avatar.js'

const props = defineProps({
  character: { type: Object, required: true },
})

const { chatFieldRef, friend, openChat } = useOpenChat()
</script>

<template>
  <article
    class="group relative h-88 md:h-104 w-full cursor-pointer overflow-hidden rounded-panel shadow-stage transition-transform duration-400 ease-soft hover:-translate-y-1"
    role="button"
    tabindex="0"
    :aria-label="`与精选角色${character.name}开始聊天`"
    @click="openChat(character.id)"
    @keydown.enter="openChat(character.id)"
  >
    <!-- 背景：cover 铺满，不拉伸变形 -->
    <img
      :src="character.background_image"
      @error="avatarFallback"
      :alt="`${character.name}背景`"
      class="absolute inset-0 h-full w-full object-cover transition-transform duration-400 ease-soft group-hover:scale-[1.03]"
    />
    <div class="absolute inset-0 bg-gradient-to-r from-black/75 via-black/35 to-transparent"></div>
    <div class="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/60 to-transparent"></div>

    <!-- 立绘式 photo：contain 保持比例，锚定右下 -->
    <img
      :src="character.photo"
      @error="avatarFallback"
      :alt="`${character.name}立绘`"
      class="absolute bottom-0 right-3 md:right-6 h-3/5 md:h-4/5 w-auto object-contain drop-shadow-[0_8px_24px_rgb(0_0_0/0.5)] transition-transform duration-400 ease-soft group-hover:-translate-y-1"
    />

    <div class="absolute left-0 bottom-0 max-w-[62%] p-5 md:p-7">
      <span class="badge badge-secondary badge-sm mb-2 border-0 font-bold">精选角色</span>
      <h3 class="font-display text-2xl md:text-3xl font-black text-white drop-shadow-lg line-clamp-1 break-all">
        {{ character.name }}
      </h3>
      <p class="mt-2 text-sm md:text-base text-white/85 line-clamp-2 md:line-clamp-3 break-all">
        {{ character.profile }}
      </p>
      <!-- 点击会冒泡到卡片触发 openChat，按钮本身不再重复绑定 -->
      <AppButton class="mt-4" tabindex="-1">开始聊天</AppButton>
    </div>
  </article>
  <ChatField ref="chatFieldRef" :friend="friend" />
</template>
