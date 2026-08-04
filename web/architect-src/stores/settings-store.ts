import { defineStore } from 'pinia'
import type { Locale } from '@/types'
import { i18n } from '@/i18n'

export const useArchSettingsStore = defineStore('arch-settings', {
  state: () => ({
    locale: 'zh-CN' as Locale,
    plantumlServer: 'http://127.0.0.1:8080/plantuml',
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
  },
})
