// architect 自持 shell（MS3-U1 裁决①独立化）——不再经 @topo/web-core/shell。
// SYNC-WITH: packages/web-core/src/shell/index.ts（仅导出 architect 消费面）
export {
  readLocale, writeLocale,
  readFontSize, writeFontSize, setFontSize,
  readModelPref,
} from './prefs';
export type { FontSizeTarget } from './prefs';
export { default as AppToolbar } from './AppToolbar.vue';
export { default as ModelSettingsDropdown } from './ModelSettingsDropdown.vue';
export type { ModelSettingsProvider, ModelInfo } from './model-provider';
export { tShell } from './i18n';
