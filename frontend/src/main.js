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

app.mount('#app')
