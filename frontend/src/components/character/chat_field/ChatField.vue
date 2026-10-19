<script setup lang="js">
import {computed, nextTick, ref, useTemplateRef} from "vue";
import InputField from "@/components/character/chat_field/input_field/InputField.vue";
import CharacterPhotoField from "@/components/character/chat_field/character_photo_field/CharacterPhotoField.vue";
import ChatHistory from "@/components/character/chat_field/chat_history/ChatHistory.vue";
import ConversationManager from './ConversationManager.vue';

const props = defineProps(['friend'])
const modalRef = useTemplateRef('modal-ref')
const inputRef = useTemplateRef('input-ref')
const history = ref([])
const managing = ref(false)
const historyVersion = ref(0)
const chatHistoryRef = useTemplateRef('chat-history-ref')

async function showModal() {
  modalRef.value.showModal()

  await nextTick()
  inputRef.value.focus()
}

const modalStyle = computed(() => {
  if (props.friend) {
    return {
      backgroundImage: `url(${props.friend.character.background_image})`,
      backgroundSize: 'cover',
      backgroundPosition: 'center',
      backgroundRepeat: 'no-repeat',
    }
  } else {
    return {}
  }
})

function handleClose() {
  inputRef.value?.close()
  modalRef.value.close()
}

function handlePushBackMessage(msq) {
  history.value.push(msq)
  chatHistoryRef.value.scrollToBottom()
}

function handleAddToLastMessage(delta) {
  if (!history.value.length) return
  history.value.at(-1).content += delta
  chatHistoryRef.value.scrollToBottom()
}

function finishMessage(status) {
  const last = history.value.at(-1)
  if (last?.role === 'ai') last.status = status
}

function handlePushFrontMessage(msq) {
  history.value.unshift(msq)
}

function handleQuickReply(text) {
  inputRef.value.sendQuick(text)
}

function openManager() {
  inputRef.value?.close()
  managing.value = true
}

function resetHistory() {
  history.value = []
  historyVersion.value++
}

defineExpose({
  showModal,
})
</script>

<template>
  <dialog ref="modal-ref" class="modal" @close="inputRef?.close()">
    <div class="modal-box w-90 max-w-[calc(100vw-1rem)] h-150 max-h-[calc(100dvh-2rem)] p-0" :style="modalStyle">
      <button @click="handleClose" aria-label="关闭聊天" class="btn btn-sm btn-circle btn-ghost bg-black/30 text-white absolute right-1 top-1 z-20">✕</button>
      <ChatHistory
          ref="chat-history-ref"
          :key="historyVersion"
          v-if="friend"
          :history="history"
          :friendId="friend.id"
          :character="friend.character"
          @pushFrontMessage="handlePushFrontMessage"
          @pushBackMessage="handlePushBackMessage"
          @quickReply="handleQuickReply"
      />
      <InputField
          v-if="friend"
          ref="input-ref"
          :friendId="friend.id"
          @pushBackMessage="handlePushBackMessage"
          @addToLastMessage="handleAddToLastMessage"
          @finishMessage="finishMessage"
      />
      <CharacterPhotoField v-if="friend" :character="friend.character" />
      <button v-if="friend" type="button" class="absolute right-2 top-12 btn btn-xs z-10" @click="openManager">记忆与记录</button>
      <ConversationManager v-if="friend && managing" :friendId="friend.id" @close="managing=false" @cleared="resetHistory" />
    </div>
  </dialog>
</template>

<style scoped>

</style>
