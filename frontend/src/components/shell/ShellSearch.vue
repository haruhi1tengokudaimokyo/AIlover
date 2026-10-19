<script setup lang="js">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SearchIcon from '@/components/navbar/Icon/SearchIcon.vue'

const props = defineProps({
  buttonClass: { type: String, default: 'btn btn-ghost btn-circle' },
})

const router = useRouter()
const route = useRoute()
const open = ref(false)
const query = ref('')
const inputRef = ref(null)

async function openSearch() {
  query.value = route.query.q || ''
  open.value = true
  document.addEventListener('keydown', onKeydown)
  await nextTick()
  inputRef.value?.focus()
}

function closeSearch() {
  open.value = false
  document.removeEventListener('keydown', onKeydown)
}

function onKeydown(event) {
  if (event.key === 'Escape') closeSearch()
}

function handleSearch() {
  const q = query.value.trim()
  closeSearch()
  router.push({ name: 'homepage-index', query: q ? { q } : {} })
}

onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))

watch(
  () => route.query.q,
  newQ => {
    if (!open.value) query.value = newQ || ''
  },
)
</script>

<template>
  <button type="button" :class="props.buttonClass" aria-label="搜索" @click="openSearch">
    <SearchIcon />
  </button>

  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-start justify-center px-4 pt-24" role="dialog" aria-modal="true" aria-label="搜索">
      <div class="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in" @click="closeSearch"></div>
      <form
        class="relative w-full max-w-lg rounded-panel bg-surface shadow-stage p-2 flex items-center gap-2 animate-rise-in"
        @submit.prevent="handleSearch"
      >
        <span class="pl-3 text-text-dim" aria-hidden="true"><SearchIcon /></span>
        <input
          ref="inputRef"
          v-model="query"
          type="search"
          class="input input-ghost grow bg-transparent focus:outline-none"
          placeholder="搜索你感兴趣的角色"
          aria-label="搜索角色"
        />
        <button type="submit" class="btn btn-primary btn-sm">搜索</button>
      </form>
    </div>
  </Teleport>
</template>
