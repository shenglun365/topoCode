// @topo/web-core — TopoCode 前端核心基础框架
// 单一契约源 + 传输层 + HTTP 客户端 + i18n 基建 + 共享组件。
// 各 app 通常通过深路径引用，此聚合导出为便捷入口。（MS3-U5/U6 注：ipc/browser-api/useComponentId 已下沉 workbench）

// 契约类型
export type {
  Project,
  Task,
  ChatSession,
  ChatMessage,
  ModelConfig,
  Draft,
  GraphNode,
  GraphEdge,
  CommunityDoc,
  CommunityChild,
  ToolCall,
} from './types/domain'

// 传输层

// HTTP 客户端
export { get, post, put, del } from './services/api'

// i18n 基建
export {
  createAppI18n,
  detectLocale,
  localeNames,
  saveLocale,
  LOCALE_KEY,
  LEGACY_LOCALE_KEY,
} from './i18n/setup'
export type { SupportedLocale } from './i18n/setup'

// 共享 composables
export { useDialog } from './composables/useDialog'
export type { DialogState } from './composables/useDialog'
export { useToast } from './composables/useToast'
export { useFloatDrag } from './composables/useFloatDrag'
