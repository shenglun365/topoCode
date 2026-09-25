/**
 * 资产工作区 · 总装（MS6-W1）。
 * 组装八域 composable 并接线跨域 watch；SFC 仅保留 setup 生命周期钩子
 * (窗口事件/会话钩子注册/轮询接管)与模板。纯移动重构：逻辑与源文件逐行对应。
 */
import { inject, provide, watch } from 'vue'
import type { InjectionKey } from 'vue'
import { useAssetCore, type WsDeps } from './useAssetCore'
import { useAssetChat } from './useAssetChat'
import { useAssetDiff } from './useAssetDiff'
import { useFramework } from './useFramework'
import { useUnownedExtract } from './useUnownedExtract'
import { useSyncExtract } from './useSyncExtract'
import { usePurgeBatch } from './usePurgeBatch'
import { useGraphTabs } from './useGraphTabs'

/** 面板注入键：SFC provide，子面板 inject 同一工作区实例(每挂载一套状态)。 */
export const ASSET_WS_KEY: InjectionKey<AssetWorkspace> = Symbol('asset-workspace')

export function useAssetWorkspace() {
  const D: WsDeps = {}

  D.core = useAssetCore(D)
  D.chat = useAssetChat(D)
  D.diff = useAssetDiff(D)
  D.framework = useFramework(D)
  D.unowned = useUnownedExtract(D)
  D.sync = useSyncExtract(D)
  D.purgeBatch = usePurgeBatch(D)
  D.graph = useGraphTabs(D)

  // 范围筛选变化 → 按选中组件重新查询(服务端 scope 过滤)；批量预览作废
  watch(D.core.scopeSel, () => {
    D.purgeBatch.batchAction.value = ''
    D.purgeBatch.batchPreview.value = null
    if (D.core.tab.value === 'semantic') D.core.loadSemantic()
  })

  // 搜索词防抖自动查询(300ms)——筛选下拉均为 @change 即时提交, 搜索框对齐同体验
  let qDebounce: ReturnType<typeof setTimeout> | null = null
  watch(D.core.q, () => {
    if (qDebounce) clearTimeout(qDebounce)
    qDebounce = setTimeout(() => {
      qDebounce = null
      if (D.core.tab.value !== 'graph' && D.core.tab.value !== 'overview') D.core.loadSemantic()
    }, 300)
  })

  // 载入哨兵 IntersectionObserver(滚动容器随 tab 切换可能重挂载)
  let capObserver: IntersectionObserver | null = null
  watch(D.core.loadMoreSentinel, (el) => {
    capObserver?.disconnect()
    if (!el) return
    capObserver = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) D.core.renderCap.value += 300
    }, { root: D.core.semScrollEl.value ?? undefined, rootMargin: '800px 0px' })
    capObserver.observe(el)
  })
  function disposeObserver() {
    capObserver?.disconnect()
    capObserver = null
  }

  return {
    ...D.core,
    ...D.chat,
    ...D.diff,
    ...D.framework,
    ...D.unowned,
    ...D.sync,
    ...D.purgeBatch,
    ...D.graph,
    disposeObserver,
  }
}

export type AssetWorkspace = ReturnType<typeof useAssetWorkspace>

/** 面板侧取用(由 SFC provide)。 */
export function useAssetWorkspaceCtx(): AssetWorkspace {
  const ws = inject(ASSET_WS_KEY)
  if (!ws) throw new Error('AssetWorkspace 未由宿主 provide')
  return ws
}
