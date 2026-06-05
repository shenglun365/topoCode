import type { ThemeType, CustomTheme, ThemeColors, ThemeFonts } from '@/types'

const STORAGE_KEY = 'topoone-custom-themes'
const ACTIVE_KEY = 'topoone-active-theme'

const CSS_VAR_MAP: Record<keyof ThemeColors, string> = {
  bgPrimary: '--bg-primary', bgSecondary: '--bg-secondary', bgTertiary: '--bg-tertiary',
  bgHover: '--bg-hover', bgActive: '--bg-active',
  textPrimary: '--text-primary', textSecondary: '--text-secondary', textMuted: '--text-muted',
  accent: '--accent', accentHover: '--accent-hover',
  success: '--success', warning: '--warning', error: '--error',
  border: '--border', borderLight: '--border-light',
}

const FONT_VAR_MAP: Record<keyof ThemeFonts, string> = {
  fontSans: '--font-sans', fontMono: '--font-mono',
}

export function useThemeEngine() {
  function loadCustomThemes(): CustomTheme[] {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  }

  function loadActiveThemeId(): string | null {
    try {
      return localStorage.getItem(ACTIVE_KEY)
    } catch {
      return null
    }
  }

  function saveCustomThemes(themes: CustomTheme[]) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(themes))
  }

  function applyTheme(themeValue: ThemeType, activeId: string) {
    document.documentElement.setAttribute('data-theme', themeValue)
    localStorage.setItem('theme', themeValue)
    localStorage.setItem(ACTIVE_KEY, activeId)
  }

  function applyCustomTheme(themeId: string, target: CustomTheme) {
    if (themeId === 'dark' || themeId === 'light') {
      document.documentElement.setAttribute('data-theme', themeId)
      localStorage.setItem('theme', themeId)
      localStorage.setItem(ACTIVE_KEY, themeId)
      return
    }
    const root = document.documentElement
    root.removeAttribute('data-theme')
    for (const [key, cssVar] of Object.entries(CSS_VAR_MAP)) {
      const value = target.colors[key as keyof ThemeColors]
      if (value) root.style.setProperty(cssVar, value)
    }
    for (const [key, cssVar] of Object.entries(FONT_VAR_MAP)) {
      const value = target.fonts[key as keyof ThemeFonts]
      if (value) root.style.setProperty(cssVar, value)
    }
    localStorage.setItem(ACTIVE_KEY, themeId)
  }

  function resetCssVars() {
    const root = document.documentElement
    for (const cssVar of Object.values(CSS_VAR_MAP)) root.style.removeProperty(cssVar)
    for (const cssVar of Object.values(FONT_VAR_MAP)) root.style.removeProperty(cssVar)
  }

  return { loadCustomThemes, loadActiveThemeId, saveCustomThemes, applyTheme, applyCustomTheme, resetCssVars }
}
