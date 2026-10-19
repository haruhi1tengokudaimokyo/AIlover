<script setup lang="js">
import {ref} from "vue";
import api from "@/js/http/api.js";
import {useUserStore} from "@/stores/user";
import {useRouter} from "vue-router";
import AppPanel from "@/design/AppPanel.vue";
import AppButton from "@/design/AppButton.vue";

const username = ref('')
const password = ref('')
const passwordConfirm = ref('')
const errorMessage = ref('')
const isSubmitting = ref(false)

const user = useUserStore()
const router = useRouter()

async function handleRegister() {
  errorMessage.value = ''
  if (!username.value.trim()) {
    errorMessage.value = '用户名不能为空'
  }
  else if (!password.value.trim()) {
    errorMessage.value = '密码不能为空'
  }else if (password.value.trim()!==passwordConfirm.value.trim()) {
    errorMessage.value = '两次输入的密码不一致'
  }
    else{
    isSubmitting.value = true
    try{
      const res = await api.post('/api/user/account/register/',{
        username: username.value,
        password: password.value,
      })
      const data = res.data
      if(data.result === 'success'){
        user.setAccessToken(data.access)
        user.setUserInfo(data)
        await router.push({
          name: 'homepage-index',
        })
      }else{
        errorMessage.value = data.result
      }
    }catch(err){
    } finally {
      isSubmitting.value = false
    }
  }
}
</script>

<template>
  <div class="relative flex min-h-[70vh] items-center justify-center px-4 py-12">
    <div
      class="pointer-events-none absolute inset-x-0 top-0 mx-auto h-64 max-w-xl rounded-full bg-rose/15 blur-3xl"
      aria-hidden="true"
    ></div>
    <AppPanel elevated class="relative w-full max-w-sm animate-rise-in">
      <h1 class="text-xl font-black text-center">创建账号</h1>
      <p class="text-sm text-text-dim text-center mt-1 mb-5">注册后即可与角色聊天</p>
      <form @submit.prevent="handleRegister" class="fieldset">

        <label class="label">用户名</label>
        <input v-model="username" type="text" class="input w-full" placeholder="用户名" />

        <label class="label">密码</label>
        <input v-model="password" type="password" class="input w-full" placeholder="密码" />

        <label class="label">确认密码</label>
        <input v-model="passwordConfirm" type="password" class="input w-full" placeholder="确认密码" />

        <p v-if="errorMessage" class="text-sm text-error mt-1">{{errorMessage}}</p>

        <AppButton type="submit" block class="mt-4" :loading="isSubmitting">注册</AppButton>
        <div class="flex justify-end mt-2">
          <RouterLink :to="{name: 'user-account-login-index'}" class="btn btn-sm btn-ghost text-text-dim">已有账号？去登录</RouterLink>
        </div>
      </form>
    </AppPanel>
  </div>
</template>

<style scoped>

</style>
