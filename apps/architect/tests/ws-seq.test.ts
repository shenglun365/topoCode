/**
 * W1-3 ArchWs seq 防护 — 迟到/乱序事件丢弃 + 无 seq 回退兼容。
 * 用假 WebSocket(不吃网络)直测 onmessage 分支。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  sent: any[] = []
  constructor(public url: string) { FakeWebSocket.instances.push(this) }
  send(d: string): void { this.sent.push(JSON.parse(d)) }
  close(): void { this.onclose?.() }
  /** 测试注入: 模拟服务端帧。 */
  feed(obj: unknown): void { this.onmessage?.({ data: JSON.stringify(obj) }) }
}

vi.stubGlobal('WebSocket', FakeWebSocket)

import { ArchWs } from '../src/services/ws-client'

beforeEach(() => { FakeWebSocket.instances = [] })

/** 构造 ArchWs 并触发假连接打开(ready() 需要 onopen)。 */
function openWs(path: string): { ws: ArchWs; fake: FakeWebSocket } {
  const ws = new ArchWs(path)
  const fake = FakeWebSocket.instances.at(-1)!
  fake.onopen?.()
  return { ws, fake }
}

describe('ArchWs seq 防护 (W1-3)', () => {
  it('迟到 seq 事件被丢弃, 新鲜事件按序分发', async () => {
    const { ws, fake } = openWs('ws/unit-test')
    await ws.ready()

    const seen: string[] = []
    ws.on('chunk', (m) => seen.push(m.delta))
    ws.onAny(() => { /* any 面同样不应收到迟到帧 */ })

    fake.feed({ type: 'chunk', delta: 'a', seq: 2 })
    fake.feed({ type: 'chunk', delta: 'stale', seq: 1 })   // 迟到 → 丢弃
    fake.feed({ type: 'chunk', delta: 'b', seq: 3 })
    expect(seen).toEqual(['a', 'b'])
    expect(ws.droppedStale).toBe(1)
    expect(ws.lastSeq).toBe(3)
    ws.close()
  })

  it('同 seq 重复帧丢弃(幂等)', async () => {
    const { ws, fake } = openWs('ws/unit-test')
    await ws.ready()
    const seen: number[] = []
    ws.on('status', (m) => seen.push(m.seq))
    fake.feed({ type: 'status', status: 'running', seq: 5 })
    fake.feed({ type: 'status', status: 'running', seq: 5 })  // 重复 → 丢弃
    expect(seen).toEqual([5])
    expect(ws.droppedStale).toBe(1)
    ws.close()
  })

  it('无 seq 事件回退兼容(老后端/pong 帧)', async () => {
    const { ws, fake } = openWs('ws/unit-test')
    await ws.ready()
    const seen: string[] = []
    ws.on('pong', () => seen.push('pong'))
    ws.on('chunk', (m) => seen.push(m.delta))
    fake.feed({ type: 'pong' })                       // 无 seq → 照常分发
    fake.feed({ type: 'chunk', delta: 'x', seq: 1 })  // seq 从 1 起, 正常
    fake.feed({ type: 'chunk', delta: 'y' })          // 混合无 seq 帧 → 照常分发
    expect(seen).toEqual(['pong', 'x', 'y'])
    expect(ws.droppedStale).toBe(0)
    ws.close()
  })
})
