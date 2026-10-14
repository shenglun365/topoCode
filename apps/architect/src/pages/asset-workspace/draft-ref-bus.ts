/**
 * 草稿引用总线：卡片内容选中 → 「引用」到右侧草稿（invalidate-bus 同模式）。
 *
 * 发布：代码资产卡/符号详情卡/逻辑资产卡的选区浮条「引用」按钮。
 * 订阅：DraftDock——有打开中的 editing 草稿则追加，否则新建后追加。
 */
export interface DraftRefSource {
  projectId?: string
  /** 组件 id(资产 scopeKey, comm-… 形态)。 */
  compId?: string
  /** 文件 id = 从项目根开始的相对路径。 */
  fileId?: string
  fileLabel?: string
  assetId?: string
  assetName?: string
  symbolName?: string
  lineStart?: number
  lineEnd?: number
  /** 逻辑资产卡：视图 + 核心资产。 */
  viewId?: string
  viewName?: string
  coreAssetId?: string
}

export interface DraftRefPayload {
  /** 选中内容(纯文本)。 */
  text: string
  /** fence 语言(文件扩展名推)。 */
  lang?: string
  source: DraftRefSource
}

type Listener = (p: DraftRefPayload) => void
const listeners = new Set<Listener>()

export function requestDraftRef(p: DraftRefPayload): void {
  for (const fn of listeners) {
    try { fn(p) } catch { /* 订阅方异常不拖垮总线 */ }
  }
}

export function onDraftRef(fn: Listener): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}
