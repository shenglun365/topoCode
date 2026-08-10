import { defineStore } from 'pinia'
import type { Locale } from '@/types'
import { i18n } from '@/i18n'

export const FONT_SCALES = [
  1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3,
] as const

export type FontScale = (typeof FONT_SCALES)[number]

export const useArchSettingsStore = defineStore('arch-settings', {
  state: () => ({
    locale: 'zh-CN' as Locale,
    plantumlServer: 'http://127.0.0.1:8080/plantuml',
    fontScale: 1 as FontScale,
  }),
  persist: true,
  actions: {
    setLocale(locale: Locale) {
      this.locale = locale
      i18n.global.locale.value = locale
      document.documentElement.lang = locale
    },
    initLocale() {
      this.setLocale(this.locale)
    },
    setFontScale(scale: number) {
      const clamped = Math.min(FONT_SCALES[FONT_SCALES.length - 1], Math.max(FONT_SCALES[0], scale))
      const snapped = FONT_SCALES.includes(clamped as FontScale)
        ? (clamped as FontScale)
        : (FONT_SCALES.reduce((a, b) => (Math.abs(b - scale) < Math.abs(a - scale) ? b : a)) as FontScale)
      this.fontScale = snapped
      document.documentElement.style.fontSize = `${Math.round(snapped * 16 * 100) / 100}px`
    },
    initFontScale() {
      this.setFontScale(this.fontScale)
    },
  },
})
