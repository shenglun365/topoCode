import { createI18n } from 'vue-i18n'
import { readLocale } from '@topo/web-core/shell'
import type { SupportedLocale } from '@topo/web-core/i18n/setup'
import zhCN from './zh-CN'
import enUS from './en-US'

/**
 * chat i18n（R3 修正）：初始 locale 读 web-core 共享键 `topoone-locale`
 * （与 workbench/architect/docs 同源），不再硬编码 zh-CN。
 */
export const i18n = createI18n({
  legacy: false,
  locale: readLocale() as SupportedLocale,
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})
