import zhCN from './zh-CN'
import enUS from './en-US'
import { createAppI18n } from '@topo/web-core/i18n/setup'

export type { SupportedLocale } from '@topo/web-core/i18n/setup'
export { localeNames } from '@topo/web-core/i18n/setup'

const i18n = createAppI18n({
  'zh-CN': zhCN,
  'en-US': enUS,
})

export default i18n
