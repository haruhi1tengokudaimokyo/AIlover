import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router/index.js'
import { useThemeStore } from './stores/theme.js'

const app = createApp(App)

app.use(createPinia())
app.use(router)

// 在挂载前应用主题，避免闪烁
useThemeStore().init()

// Lazy routes must resolve before App reads route.meta during session bootstrap.
router.isReady().then(() => app.mount('#app')).catch((error) => {
  console.error('AIlover page initialization failed', error)
  const root = document.getElementById('app')
  if (root) {
    root.textContent = '页面加载失败，请关闭后重新打开 AIlover。若仍失败，请查看启动日志。'
    root.style.cssText = 'padding:48px;color:#f2ede7;font:18px sans-serif;line-height:1.8'
  }
})
