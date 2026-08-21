import { ref } from 'vue'

export type ThemeMode = 'dark' | 'light'

const KEY = 'topoone-theme-architect'

export function initArchTheme(): ThemeMode {
  const mode = readArchTheme()
  document.documentElement.setAttribute('data-theme', mode)
  return mode
}

export function readArchTheme(): ThemeMode {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch (e) {
    console.error('[Theme] failed to read localStorage:', e)
  }
  return 'dark'
}

export function useArchTheme() {
  const theme = ref<ThemeMode>(readArchTheme())

  function apply(mode: ThemeMode) {
    theme.value = mode
    document.documentElement.setAttribute('data-theme', mode)
    try {
      localStorage.setItem(KEY, mode)
    } catch (e) {
      console.error('[Theme] failed to persist:', e)
    }
  }

  function toggle() {
    apply(theme.value === 'dark' ? 'light' : 'dark')
  }

  return { theme, toggle, apply }
}
