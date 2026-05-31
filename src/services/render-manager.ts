/** 统一渲染管理器 - 路由分发到 Worker / 主线程 / 后端 */

import { ref, watch, type Ref } from 'vue'
import type {
  RenderType,
  RenderResult,
  RenderData,
  RenderOptions,
  MermaidData,
  D3LayoutData,
  D3HierarchyData,
  MermaidResult,
  D3LayoutResult,
  D3HierarchyResult,
} from '@/workers/types'
// Vite 5.4.x worker.format 有 bug，改用 ?url 导入预编译的 worker
import renderWorkerUrl from '@/workers/render-worker-bundled.js?url'

// ==================== 类型 ====================

export type RenderBackend = 'worker' | 'main-thread' | 'backend'

export interface RenderTask {
  id: string
  type: RenderType
  status: 'pending' | 'running' | 'done' | 'error'
  result?: RenderResult
  error?: string
  progress: number
}

export interface RenderManagerConfig {
  backend: RenderBackend
  timeout: number
  cache: boolean
}

// ==================== 路由表 ====================

const ROUTES: Record<RenderType, RenderManagerConfig> = {
  'mermaid':      { backend: 'worker',      timeout: 15000, cache: true },
  'd3-layout':    { backend: 'worker',      timeout: 10000, cache: false },
  'd3-hierarchy': { backend: 'worker',      timeout: 10000, cache: false },
}

// ==================== Worker 管理 ====================

class WorkerPool {
  private worker: Worker | null = null
  private pending = new Map<string, {
    resolve: (r: any) => void
    reject: (e: any) => void
    timer: ReturnType<typeof setTimeout>
    onProgress?: (progress: number, phase: string) => void
  }>()
  private counter = 0

  /** 创建 Worker (懒加载) */
  private getWorker(): Worker {
    if (!this.worker) {
      this.worker = new Worker(renderWorkerUrl, { type: 'module' })

      this.worker.onmessage = (e) => {
        const msg = e.data

        // 进度消息
        if (msg.progress !== undefined && msg.progress >= 0 && msg.progress <= 100) {
          // 广播给所有等待中的任务
          for (const [key, pending] of this.pending) {
            if (pending.onProgress) {
              pending.onProgress(msg.progress, msg.phase || '')
            }
          }
          return
        }

        // 响应消息
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject, timer } = this.pending.get(msg.id)!
          this.pending.delete(msg.id)
          clearTimeout(timer)

          if (msg.error) {
            reject(new Error(msg.error))
          } else {
            resolve(msg.result)
          }
        }
      }

      this.worker.onerror = (e) => {
        console.error('[WorkerPool] Worker error:', e)
        for (const [, pending] of this.pending) {
          clearTimeout(pending.timer)
          pending.reject(new Error(`Worker error: ${e.message}`))
        }
        this.pending.clear()
      }
    }
    return this.worker
  }

  /** 发送渲染请求 */
  async call(
    type: RenderType,
    data: RenderData,
    options?: { timeout?: number; onProgress?: (progress: number, phase: string) => void }
  ): Promise<RenderResult> {
    const worker = this.getWorker()
    const id = `render-${++this.counter}`

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`Render timeout (${type}): ${options?.timeout || 10000}ms`))
      }, options?.timeout || 10000)

      this.pending.set(id, { resolve, reject, timer, onProgress: options?.onProgress })

      // Strip onProgress callback before sending to Worker (functions can't be cloned)
      const { onProgress: _, ...serializableOptions } = options || {}
      worker.postMessage({ id, type, data, options: serializableOptions })
    })
  }

  /** 终止 Worker */
  destroy(): void {
    if (this.worker) {
      this.worker.terminate()
      this.worker = null
    }
    for (const [, pending] of this.pending) {
      clearTimeout(pending.timer)
      pending.reject(new Error('Worker destroyed'))
    }
    this.pending.clear()
  }
}

// ==================== 缓存 ====================

class RenderCache {
  private cache = new Map<string, RenderResult>()
  private maxSize = 50

  get(key: string): RenderResult | undefined {
    return this.cache.get(key)
  }

  set(key: string, result: RenderResult): void {
    if (this.cache.size >= this.maxSize) {
      // 淘汰最早的
      const firstKey = this.cache.keys().next().value
      this.cache.delete(firstKey)
    }
    this.cache.set(key, result)
  }

  has(key: string): boolean {
    return this.cache.has(key)
  }

  clear(): void {
    this.cache.clear()
  }

  invalidate(type: RenderType): void {
    for (const key of this.cache.keys()) {
      if (key.startsWith(`${type}:`)) {
        this.cache.delete(key)
      }
    }
  }
}

// ==================== RenderManager ====================

class RenderManager {
  private workerPool = new WorkerPool()
  private cache = new RenderCache()
  private tasks = new Map<string, RenderTask>()

  /** 渲染 (核心方法) */
  async render<T extends RenderType>(
    type: T,
    data: RenderData,
    options?: RenderOptions & { onProgress?: (progress: number, phase: string) => void }
  ): Promise<RenderResult> {
    const config = ROUTES[type]
    const cacheKey = `${type}:${simpleHash(JSON.stringify(data))}`

    // 缓存命中
    if (options?.cache !== false && config.cache && this.cache.has(cacheKey)) {
      return this.cache.get(cacheKey)!
    }

    // 创建任务
    const taskId = `task-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    const task: RenderTask = {
      id: taskId,
      type,
      status: 'running',
      progress: 0,
    }
    this.tasks.set(taskId, task)

    try {
      let result: RenderResult

      switch (config.backend) {
        case 'worker':
          result = await this.workerPool.call(type, data, {
            timeout: config.timeout,
            onProgress: options?.onProgress,
          })
          break

        case 'backend':
          result = await this.renderInBackend(type, data)
          break

        case 'main-thread':
          result = await this.renderInMainThread(type, data)
          break

        default:
          throw new Error(`Unknown backend: ${config.backend}`)
      }

      // 缓存结果
      if (config.cache) {
        this.cache.set(cacheKey, result)
      }

      task.status = 'done'
      task.result = result
      task.progress = 100

      return result
    } catch (error: any) {
      task.status = 'error'
      task.error = error.message
      throw error
    }
  }

  /** 响应式渲染 (返回 Ref) */
  watchRender<T extends RenderType>(
    type: T,
    data: Ref<RenderData | null>,
    options?: RenderOptions
  ): { result: Ref<RenderResult | null>; loading: Ref<boolean>; error: Ref<string | null>; progress: Ref<number> } {
    const result = ref<RenderResult | null>(null) as Ref<RenderResult | null>
    const loading = ref(false)
    const error = ref<string | null>(null)
    const progress = ref(0)

    const cancelled = false

    watch(data, async (newData) => {
      if (cancelled || !newData) {
        result.value = null
        return
      }

      loading.value = true
      error.value = null
      progress.value = 0

      try {
        const res = await this.render(type, newData, {
          ...options,
          onProgress: (p, _phase) => { progress.value = p },
        })
        result.value = res
        progress.value = 100
      } catch (e: any) {
        error.value = e.message
      } finally {
        loading.value = false
      }
    }, { immediate: true })

    return { result, loading, error, progress }
  }

  /** 后端渲染 (PlantUML 等) */
  private async renderInBackend(type: RenderType, data: RenderData): Promise<RenderResult> {
    // 通过 IPC 调用 Python 后端
    if (typeof window !== 'undefined' && window.api) {
      return window.api.backend.render({ type, data })
    }
    throw new Error('Backend render not available (no window.api)')
  }

  /** 主线程渲染 (PIXI/CSS 动画) */
  private async renderInMainThread(_type: RenderType, _data: RenderData): Promise<RenderResult> {
    // 主线程同步执行，由调用方处理
    throw new Error('Main-thread render should be handled by caller')
  }

  /** 获取任务状态 */
  getTask(id: string): RenderTask | undefined {
    return this.tasks.get(id)
  }

  /** 清除缓存 */
  clearCache(type?: RenderType): void {
    if (type) {
      this.cache.invalidate(type)
    } else {
      this.cache.clear()
    }
  }

  /** 销毁 */
  destroy(): void {
    this.workerPool.destroy()
    this.cache.clear()
    this.tasks.clear()
  }
}

// ==================== 工具函数 ====================

function simpleHash(str: string): string {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i)
    hash = ((hash << 5) - hash) + char
    hash |= 0
  }
  return Math.abs(hash).toString(36)
}

// ==================== 导出 ====================

export const renderManager = new RenderManager()

// Window API 类型扩展
declare global {
  interface Window {
    api?: {
      backend?: {
        render: (params: { type: string; data: any }) => Promise<any>
        renderPlantuml: (params: { code: string; format: string; useRemote: boolean }) => Promise<any>
      }
    }
  }
}
