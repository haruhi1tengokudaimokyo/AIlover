<script setup lang="js">
import {nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef} from "vue";
import api from "@/js/http/api.js";
import CharacterCard from "@/components/home/CharacterCard.vue";
import AppEmpty from "@/design/AppEmpty.vue";
import AppSkeleton from "@/design/AppSkeleton.vue";
import AppSpinner from "@/design/AppSpinner.vue";

const friends = ref([])
const isLoading = ref(false)
const hasFriends = ref(true)
const sentinelRef = useTemplateRef('sentinel-ref')

function checkSentinelVisible() {  // 判断哨兵是否能被看到
  if (!sentinelRef.value) return false

  const rect = sentinelRef.value.getBoundingClientRect()
  return rect.top < window.innerHeight && rect.bottom > 0
}

async function loadMore() {
  if (isLoading.value || !hasFriends.value) return
  isLoading.value = true

  let newFriends = []
  try{
    const res = await api.get('/api/friend/get_list/',{
      params: {
        items_count:friends.value.length,
      }
    })
    const data = res.data
    if (data.result === 'success') {
      newFriends = data.friends
    }
  } catch(err) {
    console.log(err)
  } finally {
    isLoading.value = false
    if (newFriends.length === 0) {
      hasFriends.value = false
    } else {
      friends.value.push(...newFriends)
      await nextTick()

      if (checkSentinelVisible()) {
        await loadMore()
      }
    }
  }
}

function removeFriend (friendId) {
  friends.value = friends.value.filter(f => f.id !== friendId)
}

let observer = null
onMounted(async () => {
  await loadMore()  // 加载新元素

  observer = new IntersectionObserver(
    entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          loadMore()
        }
      })
    },
    {root: null, rootMargin: '2px', threshold: 0}
  )

  //监听哨兵元素， 每次哨兵被看到时，都会触发一次
  if (sentinelRef.value) observer.observe(sentinelRef.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()  // 解绑监听器
})

</script>

<template>
  <div class="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8 pb-12 pt-8">
    <header class="mb-6">
      <h1 class="text-2xl font-black">好友</h1>
      <p class="text-sm text-text-dim mt-1">和你聊过的角色都在这里</p>
    </header>

    <div v-if="isLoading && friends.length === 0" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 sm:gap-5">
      <AppSkeleton variant="card" :count="8" />
    </div>

    <AppEmpty
      v-else-if="friends.length === 0"
      title="还没有好友"
      description="去首页找一个喜欢的角色，开始第一段聊天吧"
    >
      <template #action>
        <RouterLink :to="{name:'homepage-index'}" class="btn btn-primary btn-sm rounded-field">去逛逛</RouterLink>
      </template>
    </AppEmpty>

    <template v-else>
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 sm:gap-5">
        <CharacterCard
          v-for="friend in friends"
          :key="friend.id"
          :character="friend.character"
          :canRemoveFriend="true"
          :friendId="friend.id"
          @remove="removeFriend"
        />
      </div>
      <div ref="sentinel-ref" class="h-2 mt-6"></div>
      <div class="mt-4 flex justify-center">
        <AppSpinner v-if="isLoading" label="加载更多好友" />
        <p v-else-if="!hasFriends" class="text-sm text-text-dim">没有更多聊天了</p>
      </div>
    </template>
  </div>

</template>

<style scoped>

</style>
