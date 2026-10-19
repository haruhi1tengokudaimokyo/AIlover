<script setup lang="js">
import ChatField from '@/components/character/chat_field/ChatField.vue'
import RemoveIcon from '@/components/character/icons/RemoveIcon.vue'
import AppButton from '@/design/AppButton.vue'
import { useOpenChat } from '@/components/home/useOpenChat.js'
import { avatarFallback } from '@/js/utils/avatar.js'
import api from '@/js/http/api.js'

const props = defineProps({
  character: { type: Object, required: true },
  canRemoveFriend: { type: Boolean, default: false },
  friendId: { type: [Number, String], default: null },
})
const emits = defineEmits(['remove'])

const { chatFieldRef, friend, openChat } = useOpenChat()

async function handleRemoveFriend() {
  if (!window.confirm('移除这个好友并删除关联聊天和记忆？此操作无法撤销，请先导出。')) return
  try {
    const res = await api.post('/api/friend/remove/', {
      friend_id: props.friendId,
    })
    if (res.data.result === 'success') {
      emits('remove', props.friendId)
    }
  } catch (err) {
  }
}
</script>

<template>
  <article
    class="group relative w-full cursor-pointer overflow-hidden rounded-box bg-surface shadow-card transition-all duration-250 ease-soft hover:-translate-y-1.5 hover:shadow-pop focus-visible:-translate-y-1.5"
    role="button"
    tabindex="0"
    :aria-label="`与${character.name}开始聊天`"
    @click="openChat(character.id)"
    @keydown.enter="openChat(character.id)"
  >
    <div class="relative aspect-[3/4] overflow-hidden">
      <img
        :src="character.background_image"
        @error="avatarFallback"
        :alt="`${character.name}封面`"
        class="absolute inset-0 h-full w-full object-cover transition-transform duration-400 ease-soft group-hover:scale-105"
        loading="lazy"
      />
      <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-black/25 to-transparent"></div>

      <button
        v-if="canRemoveFriend"
        type="button"
        class="btn btn-circle btn-ghost btn-sm absolute right-2 top-2 bg-black/30 text-white hover:bg-black/50"
        aria-label="移除好友"
        @click.stop="handleRemoveFriend"
      >
        <RemoveIcon />
      </button>

      <div class="absolute inset-x-0 bottom-0 p-4">
        <div class="flex items-center gap-2.5">
          <div class="avatar shrink-0">
            <div class="w-10 rounded-full ring-2 ring-white/70">
              <img :src="character.photo" @error="avatarFallback" :alt="`${character.name}头像`" />
            </div>
          </div>
          <h3 class="font-bold text-white text-base line-clamp-1 break-all drop-shadow">{{ character.name }}</h3>
        </div>
        <p class="mt-2 text-sm text-white/80 line-clamp-2 break-all">{{ character.profile }}</p>
        <div class="mt-3 opacity-0 translate-y-1 transition-all duration-250 ease-soft group-hover:opacity-100 group-hover:translate-y-0">
          <!-- 点击会冒泡到卡片触发 openChat，按钮本身不再重复绑定 -->
          <AppButton size="sm" tabindex="-1">开始聊天</AppButton>
        </div>
      </div>
    </div>
  </article>
  <ChatField ref="chatFieldRef" :friend="friend" />
</template>
