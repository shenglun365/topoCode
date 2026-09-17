/**
 * 会话大纲条目标题缩略缓存(K3 浮窗) —— LS 持久化。
 *
 * 结构: { [convId]: { [msgId]: short } } 两级——按会话整体清理(会话删除)与
 * 按消息清理(单条删除/回退)都是 O(1)。会话键做 LRU(put 触达移尾, 超上限剪最旧),
 * 防长期使用 LS 无限增长。缩略由后端 /sessions/outline/abbreviate 按需补算。
 */
const KEY = 'arch.session.outline.abbr'
const MAX_CONVS = 100

type AbbrTree = Record<string, Record<string, string>>

function read(): AbbrTree {
  try {
    const raw = localStorage.getItem(KEY)
    const t = raw ? JSON.parse(raw) : null
    return t && typeof t === 'object' ? t as AbbrTree : {}
  } catch { /* 损坏即重建 */ }
  return {}
}

function write(tree: AbbrTree): void {
  try { localStorage.setItem(KEY, JSON.stringify(tree)) } catch { /* 配额满静默 */ }
}

export const outlineAbbrCache = {
  get(convId: string, msgId: string): string {
    if (!convId || !msgId) return ''
    return read()[convId]?.[msgId] || ''
  },

  put(convId: string, msgId: string, short: string): void {
    if (!convId || !msgId || !short) return
    const tree = read()
    const bucket = tree[convId] ?? {}
    delete tree[convId]                     // LRU: 触达会话移到插入序尾部
    bucket[msgId] = short
    tree[convId] = bucket
    const keys = Object.keys(tree)
    for (const k of keys.slice(0, Math.max(0, keys.length - MAX_CONVS))) delete tree[k]
    write(tree)
  },

  removeMessages(convId: string, msgIds: string[]): void {
    if (!convId || !msgIds.length) return
    const tree = read()
    const bucket = tree[convId]
    if (!bucket) return
    let dirty = false
    for (const id of msgIds) {
      if (id in bucket) { delete bucket[id]; dirty = true }
    }
    if (dirty) write(tree)
  },

  removeConversation(convId: string): void {
    if (!convId) return
    const tree = read()
    if (!(convId in tree)) return
    delete tree[convId]
    write(tree)
  },
}
