import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import type { ThemeType, CustomTheme, ThemeColors, ThemeFonts } from '@/types'

/** CSS 变量映射表 */
const CSS_VAR_MAP: Record<keyof ThemeColors, string> = {
  bgPrimary: '--bg-primary',
  bgSecondary: '--bg-secondary',
  bgTertiary: '--bg-tertiary',
  bgHover: '--bg-hover',
  bgActive: '--bg-active',
  textPrimary: '--text-primary',
  textSecondary: '--text-secondary',
  textMuted: '--text-muted',
  accent: '--accent',
  accentHover: '--accent-hover',
  success: '--success',
  warning: '--warning',
  error: '--error',
  border: '--border',
  borderLight: '--border-light',
}

const FONT_VAR_MAP: Record<keyof ThemeFonts, string> = {
  fontSans: '--font-sans',
  fontMono: '--font-mono',
}

/** 内置暗色主题 (Catppuccin Mocha) */
const BUILTIN_DARK: CustomTheme = {
  id: 'dark',
  name: 'Catppuccin Mocha',
  description: '内置暗色主题',
  isBuiltIn: true,
  colors: {
    bgPrimary: '#1e1e2e',
    bgSecondary: '#181825',
    bgTertiary: '#313244',
    bgHover: '#45475a',
    bgActive: '#585b70',
    textPrimary: '#cdd6f4',
    textSecondary: '#a6adc8',
    textMuted: '#6c7086',
    accent: '#89b4fa',
    accentHover: '#74c7ec',
    success: '#a6e3a1',
    warning: '#f9e2af',
    error: '#f38ba8',
    border: '#45475a',
    borderLight: '#585b70',
  },
  fonts: {
    fontSans: "'Segoe UI', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', system-ui, sans-serif",
    fontMono: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace",
  },
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
}

/** 内置亮色主题 (Catppuccin Latte) */
const BUILTIN_LIGHT: CustomTheme = {
  id: 'light',
  name: 'Catppuccin Latte',
  description: '内置亮色主题',
  isBuiltIn: true,
  colors: {
    bgPrimary: '#eff1f5',
    bgSecondary: '#e6e9ef',
    bgTertiary: '#ccd0da',
    bgHover: '#bcc0cc',
    bgActive: '#acb0be',
    textPrimary: '#4c4f69',
    textSecondary: '#5c5f77',
    textMuted: '#8c8fa1',
    accent: '#1e66f5',
    accentHover: '#2a6ef5',
    success: '#40a02b',
    warning: '#df8e1d',
    error: '#d20f39',
    border: '#acb0be',
    borderLight: '#9ca0b0',
  },
  fonts: {
    fontSans: "'Segoe UI', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', system-ui, sans-serif",
    fontMono: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace",
  },
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
}

const STORAGE_KEY = 'topoone-custom-themes'
const ACTIVE_KEY = 'topoone-active-theme'

export const useThemeStore = defineStore('theme', () => {
  // State
  const theme = ref<ThemeType>('dark')
  const activeThemeId = ref<string>('dark')
  const customThemes = ref<CustomTheme[]>([])

  // Init
  function init() {
    // 加载自定义主题
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        customThemes.value = JSON.parse(saved)
      }
    } catch (e) {
      console.error('[Theme] Failed to load custom themes:', e)
    }

    // 加载当前激活的主题
    const savedActive = localStorage.getItem(ACTIVE_KEY)
    if (savedActive) {
      activeThemeId.value = savedActive
      // 兼容旧版本
      if (savedActive === 'dark' || savedActive === 'light') {
        theme.value = savedActive as ThemeType
      }
    }

    applyTheme()
  }

  // Actions
  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    activeThemeId.value = theme.value
    applyTheme()
  }

  function setTheme(t: ThemeType) {
    theme.value = t
    activeThemeId.value = t
    applyTheme()
  }

  /** 切换到指定主题 */
  function switchTheme(themeId: string) {
    const allThemes = getAllThemes()
    const target = allThemes.find(t => t.id === themeId)
    if (!target) return

    activeThemeId.value = themeId
    if (themeId === 'dark' || themeId === 'light') {
      theme.value = themeId as ThemeType
    }
    applyThemeById(themeId)
  }

  /** 创建自定义主题 */
  function createTheme(data: Omit<CustomTheme, 'id' | 'createdAt' | 'updatedAt'>): CustomTheme {
    const now = new Date().toISOString()
    const newTheme: CustomTheme = {
      ...data,
      id: `custom-${Date.now()}`,
      createdAt: now,
      updatedAt: now,
    }
    customThemes.value.push(newTheme)
    saveCustomThemes()
    return newTheme
  }

  /** 更新自定义主题 */
  function updateTheme(id: string, data: Partial<Omit<CustomTheme, 'id' | 'createdAt' | 'isBuiltIn' | 'updatedAt'>>) {
    const idx = customThemes.value.findIndex(t => t.id === id)
    if (idx === -1) return

    customThemes.value[idx] = {
      ...customThemes.value[idx],
      ...data,
      updatedAt: new Date().toISOString(),
    }
    saveCustomThemes()

    // 如果当前激活的是被修改的主题，重新应用
    if (activeThemeId.value === id) {
      applyThemeById(id)
    }
  }

  /** 删除自定义主题 */
  function deleteTheme(id: string) {
    const idx = customThemes.value.findIndex(t => t.id === id)
    if (idx === -1) return

    customThemes.value.splice(idx, 1)
    saveCustomThemes()

    // 如果删除的是当前激活的主题，切换回暗色
    if (activeThemeId.value === id) {
      switchTheme('dark')
    }
  }

  /** 导出主题为 JSON */
  function exportTheme(id: string): string {
    const allThemes = getAllThemes()
    const target = allThemes.find(t => t.id === id)
    if (!target) return ''
    return JSON.stringify(target, null, 2)
  }

  /** 从 JSON 导入主题 */
  function importTheme(json: string): CustomTheme | null {
    try {
      const data = JSON.parse(json) as CustomTheme
      // 生成新 ID 避免冲突
      const newTheme: CustomTheme = {
        ...data,
        id: `custom-${Date.now()}`,
        isBuiltIn: false,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }
      customThemes.value.push(newTheme)
      saveCustomThemes()
      return newTheme
    } catch (e) {
      console.error('[Theme] Failed to import theme:', e)
      return null
    }
  }

  /** 复制主题 */
  function duplicateTheme(id: string): CustomTheme | null {
    const allThemes = getAllThemes()
    const source = allThemes.find(t => t.id === id)
    if (!source) return null

    const now = new Date().toISOString()
    const newTheme: CustomTheme = {
      ...structuredClone(source),
      id: `custom-${Date.now()}`,
      name: `${source.name} (副本)`,
      isBuiltIn: false,
      createdAt: now,
      updatedAt: now,
    }
    customThemes.value.push(newTheme)
    saveCustomThemes()
    return newTheme
  }

  /** 获取当前激活的主题 */
  function getActiveTheme(): CustomTheme | null {
    return getThemeById(activeThemeId.value)
  }

  /** 根据 ID 获取主题 */
  function getThemeById(id: string): CustomTheme | null {
    const allThemes = getAllThemes()
    return allThemes.find(t => t.id === id) || null
  }

  /** 获取所有主题 (内置 + 自定义) */
  function getAllThemes(): CustomTheme[] {
    return [BUILTIN_DARK, BUILTIN_LIGHT, ...customThemes.value]
  }

  // Private helpers
  function saveCustomThemes() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(customThemes.value))
  }

  function applyTheme() {
    // 兼容旧版：dark/light 直接设置 data-theme
    document.documentElement.setAttribute('data-theme', theme.value)
    localStorage.setItem('theme', theme.value)
    localStorage.setItem(ACTIVE_KEY, activeThemeId.value)
  }

  function applyThemeById(themeId: string) {
    const allThemes = getAllThemes()
    const target = allThemes.find(t => t.id === themeId)
    if (!target) return

    // 内置主题走 CSS 选择器
    if (themeId === 'dark' || themeId === 'light') {
      document.documentElement.setAttribute('data-theme', themeId)
      localStorage.setItem('theme', themeId)
      localStorage.setItem(ACTIVE_KEY, themeId)
      return
    }

    // 自定义主题：动态注入 CSS 变量
    const root = document.documentElement
    // 先清除 data-theme 避免冲突
    root.removeAttribute('data-theme')

    // 应用颜色变量
    for (const [key, cssVar] of Object.entries(CSS_VAR_MAP)) {
      const value = target.colors[key as keyof ThemeColors]
      if (value) {
        root.style.setProperty(cssVar, value)
      }
    }

    // 应用字体变量
    for (const [key, cssVar] of Object.entries(FONT_VAR_MAP)) {
      const value = target.fonts[key as keyof ThemeFonts]
      if (value) {
        root.style.setProperty(cssVar, value)
      }
    }

    localStorage.setItem(ACTIVE_KEY, themeId)
  }

  /** 重置 CSS 变量 (清除自定义主题注入) */
  function resetCssVars() {
    const root = document.documentElement
    for (const cssVar of Object.values(CSS_VAR_MAP)) {
      root.style.removeProperty(cssVar)
    }
    for (const cssVar of Object.values(FONT_VAR_MAP)) {
      root.style.removeProperty(cssVar)
    }
  }

  // Watch
  watch(theme, applyTheme)

  return {
    theme,
    activeThemeId,
    customThemes,
    init,
    toggleTheme,
    setTheme,
    switchTheme,
    createTheme,
    updateTheme,
    deleteTheme,
    exportTheme,
    importTheme,
    duplicateTheme,
    getActiveTheme,
    getThemeById,
    getAllThemes,
    resetCssVars,
  }
})
