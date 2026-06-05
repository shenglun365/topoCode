/* ========================================
   Preload API 全局类型 — 对应 electron/preload.ts
   ======================================== */
export {} // make this a module so `declare global` works

/** 事件订阅: ipcRenderer.on → 返回取消订阅函数 */
type EventSub<T = unknown> = (cb: (data: T) => void) => () => void

/** 通用事件: ipcRenderer.on(channel, callback) → 返回取消订阅函数 */
type RawEventSub = (channel: string, callback: (...args: unknown[]) => void) => () => void

/** ====== 后端返回类型定义 ====== */

interface ProjectInfo {
  id: string
  name: string
  root_path: string
  language?: string
  scopes?: string[]
  scopesLabels?: string[]
  group_id?: string | null
  created_at?: string
  updated_at?: string
  file_count?: number
  total_size?: number
}

interface AnalysisTaskInfo {
  id: string
  project_id: string
  status: string
  progress: number
  scopes: string[]
  extensions: string[]
  report_types: string[]
  created_at?: string
  updated_at?: string
  error?: string
}

interface BackendStatusInfo {
  status: string
  pid?: number
  port?: number
  httpPort?: number
  httpHost?: string
  error?: string
}

interface ModelConfigInfo {
  id: string
  name: string
  provider: string
  model: string
  url: string
  type: 'local' | 'cloud'
  status?: string
  isDefault?: boolean
  temperature?: number
  maxTokens?: number
}

/* Window.api is declared in @/types/ipc.ts via IPCAPI */
