<script setup lang="js">
import Message from "@/components/character/chat_field/chat_history/message/Message.vue";
import {computed, nextTick, onBeforeUnmount, onMounted, useTemplateRef} from "vue";
import api from "@/js/http/api.js";

const props = defineProps(['history','friendId','character'])
const scrollRef = useTemplateRef('scroll-ref')
const emit = defineEmits(["pushFrontMessage", "pushBackMessage", "quickReply"]);
const sentinelRef = useTemplateRef('sentinel-ref')
let isLoading = false
let hasMessages = true
let lastMessageId = 0

function checkSentinelVisible() {  // 判断哨兵是否能被看到
  if (!sentinelRef.value) return false

  const sentinelRect = sentinelRef.value.getBoundingClientRect()
  const scrollRect = scrollRef.value.getBoundingClientRect()
  return sentinelRect.top < scrollRect.bottom && sentinelRect.bottom > scrollRect.top
}

async function loadMore() {
  if (isLoading || !hasMessages) return
  isLoading = true

  let newMessages = []
  try{
    const res = await api.get('/api/friend/message/get_history/',{
      params: {
        last_message_id:lastMessageId,
        friend_id: props.friendId,
      }
    })
    const data = res.data
    if (data.result === 'success') {
      newMessages = data.messages
    }

  }catch(err) {
    console.log(err)
  } finally {
    isLoading = false

    if (newMessages.length === 0) {
      hasMessages = false
    } else {
        const oldHeight = scrollRef.value.scrollHeight
        const oldTop = scrollRef.value.scrollTop

        for (const m of newMessages) {
          emit('pushFrontMessage', {
            role: 'ai',
            content: m.output,
            id: crypto.randomUUID(),
          })
          emit('pushFrontMessage', {
            role: 'user',
            content: m.user_message,
            id: crypto.randomUUID(),
          })
          lastMessageId = m.id
        }
        await nextTick()
        const newHeight = scrollRef.value.scrollHeight
        scrollRef.value.scrollTop = oldTop + newHeight - oldHeight

        if (checkSentinelVisible()) {
          await loadMore()
        }

    }
  }
}

let observer = null
onMounted(async () => {
  await loadMore()

  // 首次添加好友（无任何聊天记录）时，展示角色开场白
  if (props.history.length === 0 && props.character?.greeting) {
    emit('pushBackMessage', {
      role: 'ai',
      content: props.character.greeting,
      id: crypto.randomUUID(),
    })
  }

  observer = new IntersectionObserver(
      (entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            loadMore()
          }
        })
      },
      {root:null, rootMargin:"2px", threshold:0},
  )
  observer.observe(sentinelRef.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
})

// 快捷话题：仅在还没有任何用户发言时展示（开场白阶段）
const showQuickReplies = computed(() => {
  const replies = props.character?.quick_replies
  if (!Array.isArray(replies) || replies.length === 0) return false
  return !props.history.some(m => m.role === 'user')
})

function handleQuickReply(text) {
  emit('quickReply', text)
}

async function scrollToBottom(){
  await nextTick()

  scrollRef.value.scrollTop = scrollRef.value.scrollHeight
}

defineExpose({
  scrollToBottom,
})
</script>

<template>
  <div ref="scroll-ref" class="absolute top-18 left-0 w-90 h-112 overflow-y-scroll no-scrollbar">
    <div ref="sentinel-ref" class="h-2"></div>
    <Message
        v-for="message in history"
        :key="message.id"
        :message="message"
        :character="character"

    />

  </div>

  <!-- 快捷话题气泡：开场白阶段引导用户开口 -->
  <div v-if="showQuickReplies" class="absolute bottom-20 left-2 w-86 flex flex-col items-end gap-2">
    <button
        v-for="(text, i) in character.quick_replies"
        :key="i"
        @click="handleQuickReply(text)"
        class="max-w-full text-left text-sm text-white bg-black/30 backdrop-blur-sm rounded-2xl px-4 py-2 hover:bg-black/50 transition-colors"
    >
      {{ text }}
    </button>
  </div>

</template>

<style scoped>
  /* 隐藏 Chrome, Safari 和 Opera 的滚动条 */
  .no-scrollbar::-webkit-scrollbar {
    display: none;
  }

  /* 隐藏 IE, Edge 和 Firefox 的滚动条 */
  .no-scrollbar {
    -ms-overflow-style: none; /* IE and Edge */
    scrollbar-width: none; /* Firefox */
  }
</style>