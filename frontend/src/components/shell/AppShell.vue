<script setup lang="js">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user.js'
import HomePageIcon from '@/components/navbar/Icon/HomePageIcon.vue'
import FriendIcon from '@/components/navbar/Icon/FriendIcon.vue'
import CreateIcon from '@/components/navbar/Icon/CreateIcon.vue'
import SettingsIcon from '@/components/navbar/Icon/SettingsIcon.vue'
import ShellSearch from '@/components/shell/ShellSearch.vue'
import UserMenu from '@/components/shell/UserMenu.vue'

const user = useUserStore()
const route = useRoute()
const isChat = computed(() => route.name === 'chat-workspace')

const railLinkClass =
  'flex items-center justify-center size-12 rounded-box text-text-dim transition-all duration-150 ease-soft hover:text-text hover:bg-surface-2 tooltip tooltip-right'
const railActiveClass = '!text-accent bg-surface-2 shadow-card'

const tabLinkClass =
  'flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-text-dim transition-colors duration-150 ease-soft hover:text-text'
const tabActiveClass = 'text-accent'
</script>

<template>
  <div class="min-h-screen bg-canvas text-text">
    <!-- 桌面端：左侧 slim icon rail（≥lg） -->
    <aside
      class="hidden lg:flex fixed inset-y-0 left-0 z-40 w-20 flex-col items-center gap-2 border-r border-base-content/8 bg-surface/70 backdrop-blur-md py-5"
    >
      <RouterLink
        :to="{ name: 'homepage-index' }"
        class="mb-4 flex size-11 items-center justify-center rounded-box bg-gradient-to-br from-accent to-rose text-lg font-black text-primary-content shadow-card transition-transform duration-150 ease-soft hover:scale-105"
        aria-label="AIlover 首页"
      >
        AI
      </RouterLink>

      <RouterLink :to="{ name: 'homepage-index' }" :class="railLinkClass" :active-class="railActiveClass" data-tip="首页" aria-label="首页">
        <HomePageIcon />
      </RouterLink>
      <RouterLink v-if="user.isLogin()" :to="{ name: 'friend-index' }" :class="railLinkClass" :active-class="railActiveClass" data-tip="好友" aria-label="好友">
        <FriendIcon />
      </RouterLink>
      <RouterLink v-if="user.isLogin()" :to="{ name: 'create-index' }" :class="railLinkClass" :active-class="railActiveClass" data-tip="创作" aria-label="创作">
        <CreateIcon />
      </RouterLink>
      <RouterLink v-if="user.isLogin()" :to="{ name: 'settings-index' }" :class="railLinkClass" :active-class="railActiveClass" data-tip="设置" aria-label="设置">
        <SettingsIcon />
      </RouterLink>

      <ShellSearch :button-class="railLinkClass + ' tooltip tooltip-right'" />

      <div class="grow"></div>

      <UserMenu v-if="user.isLogin()" direction="up" />
      <RouterLink
        v-else-if="user.hasPulledUserInfo"
        :to="{ name: 'user-account-login-index' }"
        class="btn btn-primary btn-sm rounded-field px-3"
      >
        登录
      </RouterLink>
    </aside>

    <!-- 移动端：顶部品牌条 -->
    <header v-if="!isChat"
      class="lg:hidden sticky top-0 z-40 flex h-14 items-center gap-2 border-b border-base-content/8 bg-surface/80 backdrop-blur-md px-4"
      style="padding-top: env(safe-area-inset-top); height: calc(3.5rem + env(safe-area-inset-top))"
    >
      <RouterLink :to="{ name: 'homepage-index' }" class="flex items-center gap-2" aria-label="AIlover 首页">
        <span class="flex size-8 items-center justify-center rounded-field bg-gradient-to-br from-accent to-rose text-sm font-black text-primary-content">AI</span>
        <span class="font-black text-lg tracking-wide">AIlover</span>
      </RouterLink>
      <div class="grow"></div>
      <ShellSearch />
      <UserMenu v-if="user.isLogin()" direction="down" />
      <RouterLink
        v-else-if="user.hasPulledUserInfo"
        :to="{ name: 'user-account-login-index' }"
        class="btn btn-primary btn-sm rounded-field"
      >
        登录
      </RouterLink>
    </header>

    <!-- 页面内容 -->
    <main class="lg:pl-20 pb-20 lg:pb-0 min-h-screen">
      <slot></slot>
    </main>

    <!-- 移动端：底部 tab bar（safe-area） -->
    <nav v-if="!isChat"
      class="lg:hidden fixed bottom-0 inset-x-0 z-40 border-t border-base-content/8 bg-surface/90 backdrop-blur-md"
      style="padding-bottom: env(safe-area-inset-bottom)"
      aria-label="主导航"
    >
      <div class="flex items-stretch">
        <RouterLink :to="{ name: 'homepage-index' }" :class="tabLinkClass" :active-class="tabActiveClass" aria-label="首页">
          <HomePageIcon />
          <span class="text-[10px] font-bold">首页</span>
        </RouterLink>
        <RouterLink v-if="user.isLogin()" :to="{ name: 'friend-index' }" :class="tabLinkClass" :active-class="tabActiveClass" aria-label="好友">
          <FriendIcon />
          <span class="text-[10px] font-bold">好友</span>
        </RouterLink>
        <RouterLink v-if="user.isLogin()" :to="{ name: 'create-index' }" :class="tabLinkClass" :active-class="tabActiveClass" aria-label="创作">
          <CreateIcon />
          <span class="text-[10px] font-bold">创作</span>
        </RouterLink>
        <RouterLink v-if="user.isLogin()" :to="{ name: 'settings-index' }" :class="tabLinkClass" :active-class="tabActiveClass" aria-label="设置">
          <SettingsIcon />
          <span class="text-[10px] font-bold">设置</span>
        </RouterLink>
      </div>
    </nav>
  </div>
</template>
