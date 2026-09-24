// SYNC-WITH: packages/web-core/src/i18n/setup.ts（MS3-U1 独立化拷贝——改一方须 diff 另一方）
import { createI18n } from 'vue-i18n'

/** 支持的 locale */
export type SupportedLocale = 'zh-CN' | 'en-US'

/** 语言显示名称 */
export const localeNames: Record<SupportedLocale, string> = {
  'zh-CN': '简体中文',
  'en-US': 'English',
}

/** 从浏览器语言自动检测 */
export function detectLocale(): SupportedLocale {
  const browserLang = navigator.language.toLowerCase()
  if (browserLang.startsWith('zh')) return 'zh-CN'
  return 'en-US'
}

/** 统一语言存储键（P2）；读兼容旧键 `locale`（各 app 历史各自存储）。 */
export const LOCALE_KEY = 'topoone-locale'
export const LEGACY_LOCALE_KEY = 'locale'

/** 从 localStorage 读取上次选择的语言（优先统一键，回退旧键，再回退浏览器检测） */
function loadLocale(): SupportedLocale {
  try {
    const saved = (localStorage.getItem(LOCALE_KEY) ||
      localStorage.getItem(LEGACY_LOCALE_KEY)) as SupportedLocale
    if (saved && localeNames[saved]) return saved
  } catch {}
  return detectLocale()
}

/** 写入统一语言键（供各 app 语言切换统一入口） */
export function saveLocale(locale: SupportedLocale): void {
  try {
    localStorage.setItem(LOCALE_KEY, locale)
  } catch {}
}

/** 创建应用 i18n 实例（各 app 传入自己的词表，实例相互独立） */
export function createAppI18n<M extends Record<string, any>>(messages: M) {
  return createI18n({
    legacy: false,
    locale: loadLocale() as SupportedLocale,
    fallbackLocale: 'en-US',
    missingWarn: false,
    fallbackWarn: false,
    messages,
  })
}
