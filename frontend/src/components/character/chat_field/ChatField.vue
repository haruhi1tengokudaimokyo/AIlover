<script setup>
// Compatibility for older callers: all entry points now open the same workspace.
import { useRouter } from 'vue-router'
const props = defineProps(['friend'])
const router = useRouter()
function showModal() { if (props.friend?.id) return router.push({ name: 'chat-workspace', params: { friendId: props.friend.id } }) }
defineExpose({ showModal })
</script>
<template><span hidden></span></template>
