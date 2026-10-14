import { ref } from 'vue'

export type ThemeMode = 'dark' | 'light'

const THEME_PREFIX = 'topoone-theme-'

function themeKey(appKey: string): string {
  return `${THEME_PREFIX}${appKey}`
}

export function readTheme(appKey: string): ThemeMode {
  try {
    const saved = localStorage.getItem(themeKey(appKey))
    if (saved === 'dark' || saved === 'light') return saved
  } catch (e) {
    console.error('[Theme] failed to read localStorage:', e)
  }
  return 'dark'
}

/** 同步应用主题到 <html data-theme>，挂载前调用可避免白闪。 */
export function initTheme(appKey: string): ThemeMode {
  const mode = readTheme(appKey)
  document.documentElement.setAttribute('data-theme', mode)
  return mode
}

/** 每页独立记忆的明/暗切换（同域下以 appKey 命名空间隔离）。 */
export function useTheme(appKey: string) {
  const theme = ref<ThemeMode>(readTheme(appKey))

  function apply(mode: ThemeMode) {
    theme.value = mode
    document.documentElement.setAttribute('data-theme', mode)
    try {
      localStorage.setItem(themeKey(appKey), mode)
    } catch (e) {
      console.error('[Theme] failed to persist:', e)
    }
  }

  function toggle() {
    apply(theme.value === 'dark' ? 'light' : 'dark')
  }

  return { theme, toggle, apply }
}
