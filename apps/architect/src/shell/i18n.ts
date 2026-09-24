// SYNC-WITH: packages/web-core/src/shell/i18n.ts（MS3-U1 独立化拷贝——改一方须 diff 另一方）
import { readLocale } from './prefs'

/**
 * 统一工具栏轻量 i18n（P8-1）：随共享键 `topoone-locale` 切换。
 * 内容翻译分批接入——shell 自身控件文案先行双语，正文由各 app 后续批次接入。
 */
const ZH: Record<string, string> = {
  help: '帮助',
  font: '字号',
  language: '语言',
  model: '模型',
  context: '最大生成',
  loading: '加载中…',
  rightPanel: '右面板',
}

const EN: Record<string, string> = {
  help: 'Help',
  font: 'Font',
  language: 'Language',
  model: 'Model',
  context: 'Max Tokens',
  loading: 'Loading…',
  rightPanel: 'Right Panel',
}

export function tShell(key: string): string {
  const dict = readLocale() === 'zh-CN' ? ZH : EN
  return dict[key] ?? key
}
