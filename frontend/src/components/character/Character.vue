<script setup>
import { ref } from 'vue'
import { useUserStore } from '@/stores/user.js'
import CharacterCard from '@/components/home/CharacterCard.vue'
import api from '@/js/http/api.js'
const props = defineProps(['character', 'canEdit', 'canRemoveFriend', 'friendId'])
const emit = defineEmits(['remove'])
const user = useUserStore()
const error = ref('')
async function removeCharacter() {
  if (!window.confirm('删除这个角色及关联聊天？此操作无法撤销，请先备份。')) return
  try {
    const { data } = await api.post('/api/create/character/remove/', { character_id: props.character.id })
    if (data.result !== 'success') throw new Error(data.result)
    emit('remove', props.character.id)
  } catch (err) { error.value = err.message || '删除失败，请重试' }
}
</script>
<template>
  <div class="w-full min-w-0">
    <CharacterCard :character="character" :canRemoveFriend="!!canRemoveFriend" :friendId="friendId" @remove="emit('remove', $event)" />
    <div v-if="canEdit && character.author?.user_id === user.id" class="flex gap-2 mt-3">
      <RouterLink :to="{name:'update-character',params:{character_id:character.id}}" class="btn btn-sm btn-ghost">编辑角色</RouterLink>
      <button class="btn btn-sm btn-ghost text-error" @click="removeCharacter">删除角色</button>
    </div>
    <p v-if="error" role="alert" class="text-error text-xs">{{ error }}</p>
  </div>
</template>
