/**
 * 图数据缓存 — IndexedDB + LRU
 *
 * 以图原始数据 SHA-256 哈希前 16 位为 KEY，缓存 TopoScript 脚本。
 * 默认容量 50 条，用户可设置。
 */

// ==================== SHA-256 哈希 ====================

async function sha256hex(data: string): Promise<string> {
  const encoder = new TextEncoder()
  const dataBuffer = encoder.encode(data)
  const hashBuffer = await crypto.subtle.digest('SHA-256', dataBuffer)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('').substring(0, 16)
}

// ==================== IndexedDB 操作 ====================

const DB_NAME = 'topoone-graph-cache'
const DB_VERSION = 1
const STORE_NAME = 'toposcript'

interface CacheEntry {
  key: string
  topoScript: string
  graphDataHash: string
  createdAt: number
  accessedAt: number
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)

    request.onupgradeneeded = (event: any) => {
      const db = event.target.result as IDBDatabase
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'key' })
        store.createIndex('accessedAt', 'accessedAt', { unique: false })
      }
    }

    request.onsuccess = () => {
      resolve(request.result)
    }

    request.onerror = () => {
      reject(request.error)
    }
  })
}

async function getEntry(key: string): Promise<CacheEntry | null> {
  try {
    const db = await openDb()
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, 'readonly')
      const store = tx.objectStore(STORE_NAME)
      const request = store.get(key)
      request.onsuccess = () => resolve(request.result || null)
      request.onerror = () => resolve(null)
    })
  } catch {
    return null
  }
}

async function putEntry(entry: CacheEntry): Promise<void> {
  try {
    const db = await openDb()
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    store.put(entry)
  } catch {
    // IndexedDB 不可用时静默降级
  }
}

async function deleteEntry(key: string): Promise<void> {
  try {
    const db = await openDb()
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    store.delete(key)
  } catch {
    // 静默降级
  }
}

async function getAllEntries(): Promise<CacheEntry[]> {
  try {
    const db = await openDb()
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, 'readonly')
      const store = tx.objectStore(STORE_NAME)
      const index = store.index('accessedAt')
      const request = index.getAll()
      request.onsuccess = () => resolve(request.result || [])
      request.onerror = () => resolve([])
    })
  } catch {
    return []
  }
}

// ==================== LRU 管理 ====================

function getCacheMaxSize(): number {
  // TODO: 从设置中读取，默认 50
  return 50
}

async function evictIfOverLimit(): Promise<void> {
  const max = getCacheMaxSize()
  const entries = await getAllEntries()

  if (entries.length <= max) return

  // 按 accessedAt 排序，删除最旧的
  entries.sort((a, b) => a.accessedAt - b.accessedAt)
  const toDelete = entries.slice(0, entries.length - max)

  for (const entry of toDelete) {
    await deleteEntry(entry.key)
  }
}

// ==================== 公共 API ====================

// 缓存版本 — 递增可使旧缓存失效
const CACHE_VERSION = 'v6'

/**
 * 计算图数据的缓存 KEY
 */
export async function computeCacheKey(params: {
  taskId: string
  edgeType: string
  commLv: string
  commIds: string[]
  depth: number
}): Promise<string> {
  const raw = `${CACHE_VERSION}|${params.taskId}|${params.edgeType}|${params.commLv}|${params.commIds.join(',')}|${params.depth}`
  return sha256hex(raw)
}

/**
 * 获取缓存的 TopoScript
 */
export async function getCachedTopoScript(key: string): Promise<string | null> {
  const entry = await getEntry(key)
  if (entry) {
    // 更新访问时间
    entry.accessedAt = Date.now()
    await putEntry(entry)
    return entry.topoScript
  }
  return null
}

/**
 * 缓存 TopoScript 脚本
 */
export async function cacheTopoScript(key: string, topoScript: string, graphDataHash: string): Promise<void> {
  const entry: CacheEntry = {
    key,
    topoScript,
    graphDataHash,
    createdAt: Date.now(),
    accessedAt: Date.now(),
  }
  await putEntry(entry)
  await evictIfOverLimit()
}

/**
 * 清除缓存
 */
export async function clearCache(): Promise<void> {
  const entries = await getAllEntries()
  for (const entry of entries) {
    await deleteEntry(entry.key)
  }
}

/**
 * 获取缓存统计
 */
export async function getCacheStats(): Promise<{ count: number; maxSize: number }> {
  const entries = await getAllEntries()
  return {
    count: entries.length,
    maxSize: getCacheMaxSize(),
  }
}
