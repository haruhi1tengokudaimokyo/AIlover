<script setup lang="js">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import api from '@/js/http/api.js'
import { useRoute } from 'vue-router'
import CharacterCard from '@/components/home/CharacterCard.vue'
import HeroCharacterCard from '@/components/home/HeroCharacterCard.vue'
import RecentChats from '@/components/home/RecentChats.vue'
import AppSkeleton from '@/design/AppSkeleton.vue'
import AppEmpty from '@/design/AppEmpty.vue'
import AppButton from '@/design/AppButton.vue'
import AppSpinner from '@/design/AppSpinner.vue'
import { createLatestRequest } from '@/js/utils/latestRequest.js'

const characters = ref([])
const isLoading = ref(false)
const hasCharacters = ref(true)
const loadError = ref('')
const initialized = ref(false)
const sentinelRef = useTemplateRef('sentinel-ref')
const route = useRoute()
const latest = createLatestRequest()
let disposed = false

const searchQuery = computed(() => String(route.query.q || '').trim())
// 搜索状态下不展示精选区，全部结果进网格
const featured = computed(() => searchQuery.value ? [] : [...characters.value].sort((a, b) => Number(Boolean(b.assets?.portrait_url)) - Number(Boolean(a.assets?.portrait_url))).slice(0, 2))
const gridCharacters = computed(() => searchQuery.value ? characters.value : characters.value.filter(character => !featured.value.some(item => item.id === character.id)))

function checkSentinelVisible() {
  // 判断哨兵是否能被看到
  if (!sentinelRef.value) return false
  const rect = sentinelRef.value.getBoundingClientRect()
  return rect.top < window.innerHeight && rect.bottom > 0
}

async function loadMore() {
  if (disposed || isLoading.value || !hasCharacters.value) return
  const seq = latest.next()
  isLoading.value = true
  loadError.value = ''

  let newCharacters = null
  try {
    const res = await api.get('/api/homepage/index/', {
      params: {
        items_count: characters.value.length,
        search_query: route.query.q || '',
      },
    })
    if (!latest.isLatest(seq)) return // 过期响应直接丢弃
    const data = res.data
    if (data.result === 'success') {
      newCharacters = data.characters
    } else {
      loadError.value = '加载失败了，请稍后重试'
    }
  } catch (err) {
    if (latest.isLatest(seq)) loadError.value = '网络异常，请检查连接后重试'
    return
  } finally {
    if (latest.isLatest(seq)) isLoading.value = false
  }

  if (newCharacters === null) return
  if (newCharacters.length === 0) {
    hasCharacters.value = false
    return
  }
  characters.value.push(...newCharacters)
  await nextTick()
  if (!latest.isLatest(seq)) return
  if (checkSentinelVisible()) {
    await loadMore()
  }
}

let observer = null
onMounted(async () => {
  await loadMore()
  if (disposed) return
  initialized.value = true

  observer = new IntersectionObserver(
    entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          loadMore()
        }
      })
    },
    { root: null, rootMargin: '2px', threshold: 0 },
  )

  if (sentinelRef.value) observer.observe(sentinelRef.value)
})

function reset() {
  latest.invalidate() // 让在途请求的全部响应失效
  characters.value = []
  isLoading.value = false
  hasCharacters.value = true
  loadError.value = ''
  loadMore()
}

watch(() => route.query.q, () => {
  reset()
})

onBeforeUnmount(() => {
  disposed = true
  latest.invalidate() // 卸载后不再 set 状态
  observer?.disconnect()
})
</script>

<template>
  <div class="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8 pb-12">
    <!-- 品牌区 -->
    <section class="relative pt-10 pb-8 md:pt-14 md:pb-10 text-center" aria-label="品牌">
      <div
        class="pointer-events-none absolute inset-x-0 -top-10 mx-auto h-56 max-w-2xl rounded-full bg-accent/15 blur-3xl"
        aria-hidden="true"
      ></div>
      <h1 class="relative font-display text-4xl md:text-5xl font-black tracking-wide">
        <span class="bg-gradient-to-r from-accent to-rose bg-clip-text text-transparent">AIlover</span>
      </h1>
      <p class="relative mt-3 text-text-dim text-sm md:text-base">每一个角色，都是一段专属于你的故事</p>
    </section>

    <form class="lobby-search" @submit.prevent="$router.push({ query: { q: $event.target.elements.search.value.trim() } })">
      <span aria-hidden="true">⌕</span><input name="search" :value="searchQuery" placeholder="寻找想见的角色，或一种心动的感觉…" aria-label="搜索角色"><button>寻找角色 ↗</button>
    </form>
    <!-- 精选角色 hero 区（前 2 个角色，搜索时隐藏） -->
    <section v-if="featured.length" class="grid gap-5 md:gap-6 lg:grid-cols-2 animate-rise-in" aria-label="精选角色">
      <HeroCharacterCard v-for="character in featured" :key="character.id" :character="character" />
    </section>

    <!-- 最近聊天（好友列表，空则隐藏） -->
    <RecentChats v-if="!searchQuery" />

    <!-- 角色网格 -->
    <section class="mt-10" aria-label="角色大厅">
      <div class="flex items-end justify-between mb-4">
        <h2 class="text-lg font-bold">{{ searchQuery ? `「${searchQuery}」的搜索结果` : '角色大厅' }}</h2>
      </div>

      <!-- 首次加载骨架屏 -->
      <div v-if="!initialized && isLoading" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 sm:gap-5">
        <AppSkeleton variant="card" :count="8" />
      </div>

      <!-- 错误状态 -->
      <AppEmpty
        v-else-if="loadError && characters.length === 0"
        title="加载失败了"
        :description="loadError"
      >
        <template #action>
          <AppButton @click="reset">重新加载</AppButton>
        </template>
      </AppEmpty>

      <!-- 空状态 -->
      <AppEmpty
        v-else-if="initialized && characters.length === 0"
        :title="searchQuery ? '没有找到相关角色' : '还没有角色'"
        :description="searchQuery ? '换个关键词试试，或者去创作一个属于你的角色' : '去创作页创造第一个角色吧'"
      />

      <template v-else>
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 sm:gap-5">
          <CharacterCard v-for="character in gridCharacters" :key="character.id" :character="character" />
        </div>

        <div ref="sentinel-ref" class="h-2 mt-6"></div>
        <div class="mt-4 flex justify-center">
          <AppSpinner v-if="isLoading" label="加载更多角色" />
          <div v-else-if="loadError" class="flex items-center gap-3 text-sm text-error">
            <span>{{ loadError }}</span>
            <AppButton size="sm" variant="ghost" @click="loadMore">重试</AppButton>
          </div>
          <p v-else-if="!hasCharacters && characters.length" class="text-sm text-text-dim">没有更多角色了</p>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.lobby-search{display:flex;align-items:center;gap:12px;max-width:640px;margin:0 auto 32px;padding:8px 10px 8px 18px;border:1px solid #a89fb830;border-radius:12px;background:var(--color-surface)}.lobby-search span{font-size:25px;color:var(--color-accent)}.lobby-search input{flex:1;min-width:0;background:transparent;font-size:13px;outline:0}.lobby-search button{padding:10px 14px;background:var(--color-surface-2);border-radius:8px;font-size:12px;white-space:nowrap}@media(max-width:480px){.lobby-search input{font-size:11px}.lobby-search button{padding:9px;font-size:10px}}
</style>
