import { detectLocale } from '../i18n/setup'
import type { SupportedLocale } from '../i18n/setup'

/**
 * 跨子模块统一偏好（P2）。
 *
 * 字号 / 语言全局共享一个值；模型 / 上下文按子模块（appKey）各自记忆。
 * 旧键读兼容：语言旧键 `locale`（各 app 历史各自存储）；模型/上下文旧键
 * （chat `topoone_last_model` · `topo_context_limit`）由对应 app 自行回退。
 */

export const FONT_SIZE_KEY = 'topoone-font-size'
export const LOCALE_KEY = 'topoone-locale'
export const LEGACY_LOCALE_KEY = 'locale'
export const MODEL_PREFIX = 'topoone-model-'
export const CONTEXT_PREFIX = 'topoone-context-'

/** 统一字号档位（定稿 F1 超集） */
export const FONT_SIZES = [13, 15, 18, 22, 26, 32, 40, 48] as const
export const DEFAULT_FONT_SIZE = 16

/** 上下文容量选项（输入上下文预算，单位 token） */
export const CONTEXT_OPTIONS = [16000, 32000, 64000, 128000] as const
export const DEFAULT_CONTEXT = 32000

/** 字号 CSS 落点：`root` = <html> font-size；`--xxx` = CSS 变量 */
export type FontSizeTarget = 'root' | `--${string}`

export function readFontSize(): number {
  try {
    const v = parseInt(localStorage.getItem(FONT_SIZE_KEY) || '', 10)
    if (!Number.isNaN(v) && (FONT_SIZES as readonly number[]).includes(v)) return v
  } catch {}
  return DEFAULT_FONT_SIZE
}

export function writeFontSize(px: number): void {
  try {
    localStorage.setItem(FONT_SIZE_KEY, String(px))
  } catch {}
}

/** 写共享字号键并应用 CSS 落点（各 app 声明自己的 targets） */
export function setFontSize(px: number, targets: FontSizeTarget[] = []): void {
  writeFontSize(px)
  const root = document.documentElement
  for (const t of targets) {
    if (t === 'root') {
      root.style.fontSize = `${px}px`
    } else {
      root.style.setProperty(t, `${px}px`)
    }
  }
}

export function readLocale(): SupportedLocale {
  try {
    const saved = (localStorage.getItem(LOCALE_KEY) ||
      localStorage.getItem(LEGACY_LOCALE_KEY)) as SupportedLocale
    if (saved === 'zh-CN' || saved === 'en-US') return saved
  } catch {}
  return detectLocale()
}

export function writeLocale(locale: SupportedLocale): void {
  try {
    localStorage.setItem(LOCALE_KEY, locale)
  } catch {}
}

/** 子模块模型偏好 */
export function modelPrefKey(appKey: string): string {
  return `${MODEL_PREFIX}${appKey}`
}

export function readModelPref(appKey: string): string {
  try {
    return localStorage.getItem(modelPrefKey(appKey)) || ''
  } catch {
    return ''
  }
}

export function writeModelPref(appKey: string, modelId: string): void {
  try {
    if (modelId) localStorage.setItem(modelPrefKey(appKey), modelId)
    else localStorage.removeItem(modelPrefKey(appKey))
  } catch {}
}

/** 子模块上下文容量偏好 */
export function contextPrefKey(appKey: string): string {
  return `${CONTEXT_PREFIX}${appKey}`
}

export function readContextPref(appKey: string): number {
  try {
    const v = parseInt(localStorage.getItem(contextPrefKey(appKey)) || '', 10)
    if (!Number.isNaN(v) && v > 0) return v
  } catch {}
  return DEFAULT_CONTEXT
}

export function writeContextPref(appKey: string, tokens: number): void {
  try {
    localStorage.setItem(contextPrefKey(appKey), String(tokens))
  } catch {}
}
