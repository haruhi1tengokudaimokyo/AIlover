<script setup lang="js">

import SendIcon from "@/components/character/icons/SendIcon.vue";
import MicIcon from "@/components/character/icons/MicIcon.vue";
import {onUnmounted, ref, useTemplateRef} from "vue";
import streamApi from "@/js/http/streamApi.js";
import api from '@/js/http/api.js';
import { OrderedAudioPlayer } from '@/js/utils/orderedAudio.js';
import Microphone from "@/components/character/chat_field/input_field/Microphone.vue";
import DebugPanel from '../DebugPanel.vue';
const inputRef = useTemplateRef('input-ref')
const props = defineProps(['friendId'])
const message = ref('')
const emit = defineEmits(['pushBackMessage','addToLastMessage', 'finishMessage'])
const showMic = ref(false)
const sending = ref(false)
const status = ref('')
const failedContent = ref('')
const debugEnabled = import.meta.env.DEV && import.meta.env.VITE_ROLEPLAY_DEBUG === 'true'
const debugTrace = ref(null)
const debugGeneration = ref(null)
const voiceEnabled = ref(localStorage.getItem('ailover.voice') !== 'false')
let controller = null
let processId = 0
let generationId = null
let pendingStop = Promise.resolve()
const player = new OrderedAudioPlayer({ onError: text => status.value = text })

onUnmounted(() => {
    close();
});

function focus(){
  inputRef.value?.focus()
}

function close() {
  handleStop()
  showMic.value = false
}

async function handleSend(event, audio_msg) {
  let content
  if (audio_msg) {
    content = audio_msg.trim()
  } else{
    content = message.value.trim()
  }
  if (!content) return
  if (content.length > 2000) {
    status.value = '消息不能超过2000字';
    return;
  }
  if (sending.value || generationId) handleStop()

  status.value = ''
  debugTrace.value = null
  debugGeneration.value = null
  failedContent.value = ''
  sending.value = true
  const curId = ++processId
  const thisGeneration = crypto.randomUUID()
  generationId = thisGeneration
  message.value = ''
  let hadError = false
  try {
    await pendingStop
    if (curId !== processId) return
    controller = new AbortController()
    if (voiceEnabled.value) player.start(thisGeneration)
    emit('pushBackMessage', {role:'user' , content: content, id: crypto.randomUUID()})
    emit('pushBackMessage', {role:'ai' , content: '', status: 'pending', id: crypto.randomUUID()})
    await streamApi('/api/friend/message/chat/', {
      signal: controller.signal,
      body: {
        friend_id: props.friendId,
        message:content,
        audio: voiceEnabled.value,
        generation_id: thisGeneration,
      },
      onmessage(data,isDone) {
        if (curId !== processId) return
        if (data.generation_id && data.generation_id !== thisGeneration) return
        if (debugEnabled && data.generation_id) debugGeneration.value = data.generation_id
        if (debugEnabled && data.trace) debugTrace.value = data.trace
        if (debugEnabled && data.metrics) debugTrace.value = { ...debugTrace.value, voice: data.metrics }
        if (data.error || data.warning) status.value = data.error || data.warning
        if (data.error) {
          hadError = true
          failedContent.value = content
          emit('finishMessage', 'failed')
          player.stop()
        }
        if (isDone) {
          player.finish(thisGeneration)
          if (!hadError) emit('finishMessage', 'done')
        }
        if (data.content) {
          emit('addToLastMessage', data.content)
        }
        if (data.audio) {
          player.accept(thisGeneration, data.audio_seq, data.audio)
        }
      },
      onerror(err) {
      },
    })

  } catch(err) {
    if (curId === processId && err.name !== 'AbortError') {
      status.value = err.message || '发送失败，请重试'
      player.stop()
      failedContent.value = content
      emit('finishMessage', 'failed')
    }
  } finally {
    if (curId === processId) {
      sending.value = false
      controller = null
    }
  }
}

function handleStop() {
  if (sending.value) emit('finishMessage', 'stopped')
  const previousGeneration = generationId
  generationId = null
  ++processId
  controller?.abort()
  controller = null
  sending.value = false
  const stopped = player.stop()
  if (debugEnabled) debugTrace.value = { ...debugTrace.value, playback_stop: stopped }
  if (previousGeneration) {
    const stopVersion = processId
    const cancellation = (async () => {
      let data
      for (let attempt = 0; attempt < 4; ++attempt) {
        ;({ data } = await api.post('/api/friend/message/chat/cancel/', {
          friend_id: props.friendId, generation_id: previousGeneration,
        }))
        if (data.cleanup_complete) break
        await new Promise(resolve => setTimeout(resolve, 100))
      }
      if (debugEnabled && stopVersion === processId) debugTrace.value = { ...debugTrace.value, cancellation: data.metrics }
    })().catch(() => { /* Abort still closes SSE; an active server lease rejects overlap. */ })
    pendingStop = Promise.all([pendingStop, cancellation]).then(() => {})
  }
}

function toggleVoice() {
  voiceEnabled.value = !voiceEnabled.value
  localStorage.setItem('ailover.voice', String(voiceEnabled.value))
  if (!voiceEnabled.value) player.stop()
}

// 快捷话题：直接把话题文本作为用户消息发送
function sendQuick(text) {
  if (!text || !text.trim()) return
  message.value = text
  handleSend()
}

defineExpose({
  focus,
  close,
  sendQuick,
})
</script>

<template>
  <DebugPanel v-if="debugEnabled && debugTrace" :friendId="friendId" :generationId="debugGeneration" :trace="debugTrace" />
  <div class="absolute top-12 left-2 right-2 flex items-center gap-2 text-xs">
    <button type="button" class="btn btn-xs" @click="toggleVoice">{{ voiceEnabled ? '语音开启' : '纯文字' }}</button>
    <button v-if="sending" type="button" class="btn btn-xs" @click="handleStop">停止回复</button>
    <span v-if="sending" class="loading loading-spinner loading-xs text-white" aria-label="正在回复"></span>
  </div>
  <p v-if="status" role="status" class="absolute bottom-18 left-2 right-2 text-xs text-white bg-black/70 rounded p-2 z-10">{{ status }} <button v-if="failedContent && !sending" type="button" class="underline ml-1" @click="sendQuick(failedContent)">重试这条消息</button></p>
  <form v-if="!showMic" @submit.prevent="handleSend" class="absolute bottom-4 left-2 right-2 h-12 flex items-center">
    <input
        ref="input-ref"
        v-model="message"
        class="input bg-black/30 text-white text-base backdrop-blur-sm w-full h-full rounded-2xl pr-20"
        type="text"
        maxlength="2000"
        placeholder="文本输入……"
    >
    <button type="button" @click="handleSend" aria-label="发送新消息并打断上一轮" class="absolute right-2 w-8 h-8 flex justify-center items-center cursor-pointer">
      <SendIcon />
    </button>
    <div @click="showMic = true" class="absolute right-10 w-8 h-8 flex justify-center items-center cursor-pointer">
      <MicIcon/>
    </div>
  </form>
  <Microphone v-else @close="showMic=false" @send="handleSend" @stop="handleStop" @error="status = $event" />
</template>

<style scoped>

</style>
