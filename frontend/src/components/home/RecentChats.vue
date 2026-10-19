<script setup lang="js">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import api from '@/js/http/api.js'
import { useUserStore } from '@/stores/user.js'
import CharacterCard from '@/components/home/CharacterCard.vue'
import AppSkeleton from '@/design/AppSkeleton.vue'
import { createLatestRequest } from '@/js/utils/latestRequest.js'

const MAX_ITEMS = 8

const user = useUserStore()
const friends = ref([])
const isLoading = ref(false)
const latest = createLatestRequest()

onMounted(async () => {
  if (!user.isLogin()) return
  const seq = latest.next()
  isLoading.value = true
  try {
    const res = await api.get('/api/friend/get_list/', {
      params: { items_count: 0 },
    })
    if (!latest.isLatest(seq)) return
    const data = res.data
    if (data.result === 'success') {
      friends.value = (data.friends || []).slice(0, MAX_ITEMS)
    }
  } catch (err) {
    // 最近聊天区加载失败时静默隐藏，不打断首页主流程
  } finally {
    if (latest.isLatest(seq)) isLoading.value = false
  }
})

onBeforeUnmount(() => latest.invalidate())
</script>

<template>
  <section v-if="user.isLogin() && (isLoading || friends.length)" class="mt-10" aria-label="最近聊天">
    <h2 class="text-lg font-bold mb-4">最近聊天</h2>
    <div v-if="isLoading" class="flex gap-4 overflow-hidden">
      <div v-for="i in 4" :key="i" class="w-48 shrink-0">
        <AppSkeleton variant="card" />
      </div>
    </div>
    <div v-else class="flex gap-4 overflow-x-auto pb-2 -mx-1 px-1">
      <div v-for="friendItem in friends" :key="friendItem.id" class="w-48 sm:w-56 shrink-0">
        <CharacterCard :character="friendItem.character" />
      </div>
    </div>
  </section>
</template>
