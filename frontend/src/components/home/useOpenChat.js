import { onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user.js'
import api from '@/js/http/api.js'
export function useOpenChat() {
  const user = useUserStore()
  const router = useRouter()
  const opening = ref(false)
  const openError = ref('')
  let disposed = false
  onBeforeUnmount(() => { disposed = true })
  async function openChat(characterId) {
    if (opening.value) return
    if (!user.isLogin()) return router.push({ name: 'user-account-login-index' })
    opening.value = true
    openError.value = ''
    try {
      const { data } = await api.post('/api/friend/get_or_create/', { character_id: characterId })
      if (disposed) return
      if (data.result !== 'success') throw new Error(data.result)
      await router.push({ name: 'chat-workspace', params: { friendId: data.friend.id } })
    } catch (err) { if (!disposed) openError.value = err.response?.data?.result || err.message || '打开聊天失败，请重试' }
    finally { if (!disposed) opening.value = false }
  }
  return { openChat, opening, openError }
}
