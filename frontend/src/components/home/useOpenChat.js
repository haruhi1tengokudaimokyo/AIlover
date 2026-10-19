/**
 * 「开始聊天」唤起逻辑：未登录跳登录页；已登录 get_or_create 好友后打开 ChatField 模态。
 * 与 Character.vue 现有链路保持一致（Phase 2 才接管为 /chat 路由）。
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user.js'
import api from '@/js/http/api.js'

export function useOpenChat() {
  const user = useUserStore()
  const router = useRouter()
  const chatFieldRef = ref(null)
  const friend = ref(null)

  async function openChat(characterId) {
    if (!user.isLogin()) {
      await router.push({ name: 'user-account-login-index' })
      return
    }
    try {
      const res = await api.post('/api/friend/get_or_create/', {
        character_id: characterId,
      })
      const data = res.data
      if (data.result === 'success') {
        friend.value = data.friend
        chatFieldRef.value?.showModal()
      }
    } catch (err) {
    }
  }

  return { chatFieldRef, friend, openChat }
}
