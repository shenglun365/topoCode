/**
 * 子会话窗口唯一性锁(2026-10)——跨 tab 防同一会话多开(避免并发写/逻辑混乱)。
 *
 * 机制: localStorage 锁(tabId+ts) + 3s 心跳 / 10s 过期 + BroadcastChannel
 * 广播(抢占/释放即时通知)。dock 右侧打开天然唯一(单活跃会话); 本锁管
 * 「同一子会话在多个浏览器 tab 打开」场景。
 * 同 tab 内切换会话自动释放旧锁(beforeunload 兜底)。
 */
import { onBeforeUnmount, onMounted } from 'vue'

const CH = 'arch-conv-lock'
const HB_MS = 3000
const EXPIRE_MS = 10000

interface LockPayload { tabId: string; ts: number }

const TAB_ID = `tab-${Math.random().toString(36).slice(2, 10)}`
let channel: BroadcastChannel | null = null
const held = new Map<string, number>()          // convId → heartbeat timer

function ch(): BroadcastChannel | null {
  if (channel) return channel
  try { channel = new BroadcastChannel(CH) } catch { /* 无 BC 环境: 仅 localStorage */ }
  return channel
}

function key(id: string) { return `arch-conv-lock:${id}` }

function readLock(id: string): LockPayload | null {
  try {
    const raw = localStorage.getItem(key(id))
    if (!raw) return null
    const p = JSON.parse(raw) as LockPayload
    if (Date.now() - (p.ts || 0) > EXPIRE_MS) return null   // 过期=无主
    return p
  } catch { return null }
}

function writeLock(id: string) {
  localStorage.setItem(key(id), JSON.stringify({ tabId: TAB_ID, ts: Date.now() }))
}

export interface ConvLock {
  /** 尝试锁定; held=已在别的 tab 打开(返回 owner)时由调用方决定 接管/取消 */
  claim: (convId: string) => Promise<{ claimed: boolean; owner?: string }>
  /** 抢占(用户确认接管): 广播原持主释放 */
  takeover: (convId: string) => void
  release: (convId: string) => void
  /** 当前是否本 tab 持有 */
  isMine: (convId: string) => boolean
}

export function useConvWindowLock(): ConvLock {
  function startHeartbeat(id: string) {
    if (held.has(id)) return
    held.set(id, window.setInterval(() => {
      if (readLock(id)?.tabId === TAB_ID) writeLock(id)
    }, HB_MS))
  }

  function claim(convId: string): Promise<{ claimed: boolean; owner?: string }> {
    const cur = readLock(convId)
    if (cur && cur.tabId !== TAB_ID) {
      return Promise.resolve({ claimed: false, owner: cur.tabId })
    }
    writeLock(convId)
    startHeartbeat(convId)
    ch()?.postMessage({ type: 'claimed', convId, tabId: TAB_ID })
    return Promise.resolve({ claimed: true })
  }

  function takeover(convId: string) {
    ch()?.postMessage({ type: 'takeover', convId, from: TAB_ID })
    writeLock(convId)
    startHeartbeat(convId)
  }

  function release(convId: string) {
    const t = held.get(convId)
    if (t) { window.clearInterval(t); held.delete(convId) }
    if (readLock(convId)?.tabId === TAB_ID) localStorage.removeItem(key(convId))
    ch()?.postMessage({ type: 'released', convId, tabId: TAB_ID })
  }

  function isMine(convId: string) { return readLock(convId)?.tabId === TAB_ID }

  onMounted(() => {
    window.addEventListener('beforeunload', releaseAll)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('beforeunload', releaseAll)
    releaseAll()
  })

  function releaseAll() {
    for (const id of [...held.keys()]) release(id)
  }

  return { claim, takeover, release, isMine }
}
