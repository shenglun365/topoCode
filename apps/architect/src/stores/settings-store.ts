import { defineStore } from 'pinia'
import type { Locale } from '@/types'
import { i18n } from '@/i18n'
import {
  readLocale,
  writeLocale,
  readFontSize,
  writeFontSize,
  setFontSize,
} from '@/shell/prefs'

const LEGACY_PERSIST_KEY = 'arch-settings'

/** 迁移旧版 `arch-settings` pinia persist（{locale, fontScale}）→ 共享键，成功后清除旧键。 */
function migrateLegacy() {
  try {
    const raw = localStorage.getItem(LEGACY_PERSIST_KEY)
    if (!raw) return
    const legacy = JSON.parse(raw)
    if (legacy && typeof legacy === 'object') {
      if (legacy.locale && !localStorage.getItem('topoone-locale')) {
        writeLocale(legacy.locale as Locale)
      }
      const scale = Number(legacy.fontScale)
      if (scale > 0 && !localStorage.getItem('topoone-font-size')) {
        writeFontSize(Math.round(scale * 16))
      }
    }
    localStorage.removeItem(LEGACY_PERSIST_KEY)
  } catch {
    /* 忽略损坏数据 */
  }
}

/**
 * 全局设置（P4）：locale / 字号改由共享键记忆（`topoone-locale` · `topoone-font-size`），
 * 移除 arch-settings 持久化（旧值读兼容迁移）。字号落点 = <html> root font-size。
 */
export const useArchSettingsStore = defineStore('arch-settings', {
  state: () => {
    migrateLegacy()
    return {
      locale: readLocale() as Locale,
      fontSize: readFontSize(),
    }
  },
  actions: {
    setLocale(locale: Locale) {
      this.locale = locale
      writeLocale(locale)
      i18n.global.locale.value = locale
      document.documentElement.lang = locale
    },
    initLocale() {
      this.setLocale(this.locale)
    },
    setFontSize(px: number) {
      this.fontSize = px
      setFontSize(px, ['root'])
    },
    initFontSize() {
      this.setFontSize(this.fontSize)
    },
  },
})
