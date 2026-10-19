<script setup lang="js">
import {useUserStore} from "@/stores/user.js";
import {avatarFallback} from '@/js/utils/avatar.js';

defineProps(['message','character'])

const user = useUserStore()
</script>

<template>
  <div v-if="message.content || message.status">
    <div v-if="message.role === 'ai' " class="chat chat-start">
      <div class="chat-image avatar">
        <div class="w-10 rounded-full">
          <img :src="character.photo" alt="">
        </div>
      </div>
      <div class="chat-bubble whitespace-pre-wrap break-words">
        {{ message.content }}
        <span v-if="message.status === 'pending' && !message.content" class="loading loading-dots loading-sm" aria-label="正在回复"></span>
        <small v-if="message.status === 'failed'" class="block opacity-70">回复未完成，未保存</small>
        <small v-if="message.status === 'stopped'" class="block opacity-70">已停止</small>
      </div>
    </div>
    <div v-else class="chat chat-end">
      <div class="chat-image avatar">
        <div class="w-10 rounded-full">
          <img :src="user.photo" @error="avatarFallback" alt="用户头像">
        </div>
      </div>
      <div class="chat-bubble chat-bubble-success whitespace-pre-wrap">{{message.content}}</div>
    </div>
  </div>
</template>

<style scoped>

</style>
