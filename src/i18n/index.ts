import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN'
import enUS from './en-US'

/** 支持的 locale */
export type SupportedLocale = 'zh-CN' | 'en-US'

/** 语言显示名称 */
export const localeNames: Record<SupportedLocale, string> = {
  'zh-CN': '简体中文',
  'en-US': 'English',
}

/** 从浏览器语言自动检测 */
function detectLocale(): SupportedLocale {
  const browserLang = navigator.language.toLowerCase()
  if (browserLang.startsWith('zh')) return 'zh-CN'
  return 'en-US'
}

/** 从 localStorage 读取上次选择的语言 */
function loadLocale(): SupportedLocale {
  try {
    const saved = localStorage.getItem('locale') as SupportedLocale
    if (saved && localeNames[saved]) return saved
  } catch {}
  return detectLocale()
}

const i18n = createI18n({
  legacy: false,
  locale: loadLocale() as SupportedLocale,
  fallbackLocale: 'en-US',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

export default i18n
