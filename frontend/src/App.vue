<script setup>
import AppShell from '@/components/shell/AppShell.vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { onMounted } from 'vue'
import { useUserStore } from '@/stores/user.js'
import api from '@/js/http/api.js'

const user = useUserStore()
const router = useRouter()
const route = useRoute()
onMounted(async () => {
  try {
    const res = await api.get('/api/user/account/get_user_info/')
    const data = res.data
    if (data.result === 'success') {
      user.setUserInfo(data)
    }
  } catch (err) {
  } finally {
    user.setHasPulledUserInfo(true)
    if (route.meta.needLogin && !user.isLogin()) {
      await router.replace({
        name: 'user-account-login-index',
      })
    }
  }
})
</script>

<template>
  <AppShell>
    <RouterView />
  </AppShell>
</template>

<style scoped>
</style>
