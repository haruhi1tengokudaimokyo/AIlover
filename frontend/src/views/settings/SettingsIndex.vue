<script setup>
import { onMounted, ref } from 'vue'
import api from '@/js/http/api.js'
const config = ref(null)
const error = ref('')
const loading = ref(false)
async function load() {
  loading.value = true
  error.value = ''
  try { config.value = (await api.get('/api/settings/status/')).data }
  catch (err) { error.value = err.response?.data?.detail || '读取配置失败，请重新登录或稍后重试' }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <main class="max-w-3xl mx-auto w-full px-6 py-8">
    <h1 class="text-2xl font-bold mb-4">运行设置</h1>
    <p class="opacity-70 mb-4">配置保存在本机 .env 文件中，修改后需要重新启动应用。此页面不会显示密钥，也不会调用付费服务。</p>
    <button class="btn btn-sm mb-4" :disabled="loading" @click="load">{{ loading ? '读取中…' : '刷新状态' }}</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <dl v-if="config" class="grid grid-cols-2 gap-3 bg-base-200 p-5 rounded-xl">
      <dt>聊天模型</dt><dd class="break-words">{{ config.model }}</dd>
      <dt>模型服务</dt><dd class="break-words">{{ config.model_host }}</dd>
      <dt>模型密钥</dt><dd>{{ config.model_key_configured ? '已填写，尚需实际验证' : '未填写，暂时无法对话' }}</dd>
      <dt>语音输出</dt><dd>{{ config.tts_enabled ? '已开启' : '已关闭' }}</dd>
      <dt>语音密钥</dt><dd>{{ config.tts_key_configured ? '已填写，尚需实际验证' : '未填写' }}</dd>
      <dt>你的角色会话</dt><dd>{{ config.friend_count }}</dd>
      <dt>你的成功对话</dt><dd>{{ config.message_count }}</dd>
    </dl>
    <section class="mt-6 space-y-3">
      <h2 class="font-bold">开始使用</h2>
      <ol class="list-decimal pl-5 space-y-2">
        <li>将项目目录的 .env.example 复制为 .env，填写模型服务的 API_KEY、API_BASE 和 MODEL。</li>
        <li>先设置 TTS_ENABLED=false，重新启动应用，测试文字聊天。</li>
        <li>文字正常后再开启语音。角色原声需要可用的复刻音色，参考语音文件本身不能朗读新台词。</li>
        <li>打包版的配置文件放在 exe 旁边的 data/.env。</li>
      </ol>
      <p class="text-sm opacity-70">对话会发送到你配置的模型服务；开启语音后，回复文字也会发送到语音服务。账号、记录和记忆保存在本机。你可以在聊天窗口的「记忆与记录」里导出或清空。</p>
    </section>
  </main>
</template>
