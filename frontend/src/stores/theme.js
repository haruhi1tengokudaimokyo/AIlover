import { defineStore } from 'pinia'
import { ref } from 'vue'

const STORAGE_KEY = 'ailover.theme'
const THEMES = { dark: 'ailover-dark', light: 'ailover-light' }

export const useThemeStore = defineStore('theme', () => {
  const theme = ref('dark')

  function apply() {
    const name = THEMES[theme.value] || THEMES.dark
    document.documentElement.dataset.theme = name
    document.documentElement.style.colorScheme = theme.value === 'light' ? 'light' : 'dark'
  }

  function init() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved === 'light' || saved === 'dark') theme.value = saved
    } catch (err) {
      // localStorage 不可用时保持默认 dark
    }
    apply()
  }

  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    try {
      localStorage.setItem(STORAGE_KEY, theme.value)
    } catch (err) {
      // 忽略写入失败，内存态仍然生效
    }
    apply()
  }

  return { theme, init, toggle }
})
