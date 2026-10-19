<script setup lang="js">
import { useUserStore } from '@/stores/user.js'
import { useThemeStore } from '@/stores/theme.js'
import UserSpaceIcon from '@/components/navbar/Icon/UserSpaceIcon.vue'
import UserProfileIcon from '@/components/navbar/Icon/UserProfileIcon.vue'
import UserLogoutIcon from '@/components/navbar/Icon/UserLogoutIcon.vue'
import SunIcon from '@/components/navbar/Icon/SunIcon.vue'
import MoonIcon from '@/components/navbar/Icon/MoonIcon.vue'
import api from '@/js/http/api.js'
import { useRouter } from 'vue-router'
import { avatarFallback } from '@/js/utils/avatar.js'

const props = defineProps({
  // up：桌面 rail 底部，菜单向上弹出；down：移动端顶栏，向下弹出
  direction: { type: String, default: 'down' },
})

const user = useUserStore()
const theme = useThemeStore()
const router = useRouter()

function closeMenu() {
  const element = document.activeElement
  if (element && element instanceof HTMLElement) element.blur()
}

function handleToggleTheme() {
  theme.toggle()
  closeMenu()
}

async function handleLogout() {
  try {
    const res = await api.post('/api/user/account/logout/')
    if (res.data.result === 'success') {
      user.logout()
      closeMenu()
      await router.push({ name: 'homepage-index' })
    }
  } catch (err) {
  }
}
</script>

<template>
  <div
    class="dropdown"
    :class="props.direction === 'up' ? 'dropdown-right dropdown-end' : 'dropdown-end'"
  >
    <div tabindex="0" role="button" class="avatar btn btn-circle btn-ghost w-10 h-10" aria-label="用户菜单">
      <div class="w-8 rounded-full ring-2 ring-accent/40">
        <img :src="user.photo" @error="avatarFallback" alt="用户头像" />
      </div>
    </div>
    <ul
      tabindex="-1"
      class="dropdown-content menu bg-surface rounded-panel z-50 w-52 p-2 shadow-pop border border-base-content/8"
    >
      <li>
        <RouterLink @click="closeMenu" :to="{ name: 'user-space-index', params: { user_id: user.id } }">
          <div class="avatar">
            <div class="w-10 rounded-full">
              <img :src="user.photo" @error="avatarFallback" alt="用户头像" />
            </div>
          </div>
          <span class="text-base font-bold line-clamp-1 break-all">{{ user.username }}</span>
        </RouterLink>
      </li>
      <li>
        <RouterLink @click="closeMenu" :to="{ name: 'user-space-index', params: { user_id: user.id } }" class="text-sm font-bold py-3">
          <UserSpaceIcon />
          个人空间
        </RouterLink>
      </li>
      <li>
        <RouterLink @click="closeMenu" :to="{ name: 'user-profile-index' }" class="text-sm font-bold py-3">
          <UserProfileIcon />
          编辑资料
        </RouterLink>
      </li>
      <li>
        <button type="button" @click="handleToggleTheme" class="text-sm font-bold py-3">
          <SunIcon v-if="theme.theme === 'dark'" />
          <MoonIcon v-else />
          {{ theme.theme === 'dark' ? '切换浅色模式' : '切换深色模式' }}
        </button>
      </li>
      <li></li>
      <li>
        <a @click="handleLogout" class="text-sm font-bold py-3">
          <UserLogoutIcon />
          退出登录
        </a>
      </li>
    </ul>
  </div>
</template>
