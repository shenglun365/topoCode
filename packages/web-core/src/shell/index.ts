// @topo/web-core/shell — 统一工具栏基建（P2）
// 各子模块（/app /doc /chat /architect）共用。

export {
  FONT_SIZE_KEY,
  LOCALE_KEY,
  LEGACY_LOCALE_KEY,
  MODEL_PREFIX,
  CONTEXT_PREFIX,
  FONT_SIZES,
  DEFAULT_FONT_SIZE,
  CONTEXT_OPTIONS,
  DEFAULT_CONTEXT,
  readFontSize,
  writeFontSize,
  setFontSize,
  readLocale,
  writeLocale,
  readModelPref,
  writeModelPref,
  readContextPref,
  writeContextPref,
  modelPrefKey,
  contextPrefKey,
} from './useAppPrefs'
export type { FontSizeTarget } from './useAppPrefs'

export { default as AppToolbar } from './AppToolbar.vue'
export { default as FontSizeSelect } from './FontSizeSelect.vue'
export { default as LocaleToggle } from './LocaleToggle.vue'
export { default as HelpButton } from './HelpButton.vue'
export { default as ModelSettingsDropdown } from './ModelSettingsDropdown.vue'
export { default as PanelToggleButton } from './PanelToggleButton.vue'
export { tShell } from './i18n'

export type { ModelSettingsProvider, ModelInfo } from './model-provider'
