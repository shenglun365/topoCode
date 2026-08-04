import type { AgentMessage, AgentSession, AgentStatus, AgentToolCall, TaskNode } from '@/types'

const ASSISTANT_REPLIES = [
  '计划: 1) 建立任务入口与领域对象  2) 实现核心逻辑并接入唯一约束  3) 补齐单测与集成用例。待你确认后开始。',
  '正在实现核心逻辑…已完成主体，正在进行自测与用例补充。',
  '已按规约完成编码并提交(Conventional Commits)。',
]

const TOOL_SEQUENCE: (AgentToolCall & { delay: number })[] = [
  { type: 'write-file', label: 'app/domain.go', detail: '领域对象与不变量 96 行', ok: true, delay: 420 },
  { type: 'write-file', label: 'app/service.go', detail: '核心业务逻辑 + 幂等查重 214 行', ok: true, delay: 360 },
  { type: 'run-command', label: 'go test ./app/...', detail: '单测 14 个，通过 14', ok: true, delay: 300 },
  { type: 'run-test', label: 'tests/integration_test.go', detail: '集成用例 3 个，通过 3', ok: true, delay: 380 },
]

function buildDoneMessage(ok: boolean): AgentMessage {
  return {
    id: `m-${Date.now()}`,
    role: 'assistant',
    time: Date.now(),
    content: ok
      ? '任务完成：单测与集成用例全部通过，符合编码规约。已生成变更摘要待验收。'
      : '存在未通过用例，已标记风险项，等待你的决策或降级方案。',
  }
}

export interface RunOptions {
  onMessage?: (msg: AgentMessage) => void
  onStatus?: (status: AgentStatus) => void
  /** 任务树结构发生重大变化时回调(旧树由调用方保存后重建)。 */
  onTreeChange?: (reason: string) => void
  /** 已请求停止执行。 */
  isCancelled?: () => boolean
}

function bumpStats(session: AgentSession, bytes: number) {
  const s = session.stats ?? { requests: 0, tokensIn: 0, tokensOut: 0, bytesIn: 0, bytesOut: 0 }
  s.requests += 1
  s.bytesIn += bytes
  s.bytesOut += Math.round(bytes * 0.4)
  s.tokensIn += Math.round(bytes / 4)
  s.tokensOut += Math.round(bytes / 10)
  session.stats = s
}

export async function runMockAgentSession(session: AgentSession, task: TaskNode, opts: RunOptions = {}): Promise<void> {
  const { onMessage, onStatus, onTreeChange, isCancelled } = opts
  const push = (msg: AgentMessage) => {
    session.messages.push(msg)
    onMessage?.(msg)
  }
  const setStatus = (s: AgentStatus) => {
    session.status = s
    onStatus?.(s)
  }
  const stopCheck = () => isCancelled?.() === true

  setStatus('planning')
  bumpStats(session, 3200)
  await sleep(400)
  if (stopCheck()) return setStatus('stopped')
  push({
    id: `m-${Date.now()}`, role: 'assistant', time: Date.now(),
    content: `收到任务「${task.title}」，已加载上下文包: ${task.context.join(' / ')}。`,
  })
  await sleep(300)
  if (stopCheck()) return setStatus('stopped')
  push({
    id: `m-${Date.now()}`, role: 'assistant', time: Date.now(),
    content: ASSISTANT_REPLIES[0],
  })

  setStatus('working')
  let i = 0
  for (const step of TOOL_SEQUENCE) {
    await sleep(step.delay)
    if (stopCheck()) return setStatus('stopped')
    bumpStats(session, 2400 + i * 800)
    push({ id: `m-${Date.now()}`, role: 'tool', time: Date.now(), tool: { ...step }, content: '' })
    // 执行中偶发「任务树重构」信号(如拆分粒度不合理 → 整体废弃重建，旧树由 store 保存)
    if (i === 1 && Math.random() < 0.35) onTreeChange?.('执行中发现拆分粒度不合理，整体重建任务树(旧树缩略保存)')
    i += 1
  }

  if (stopCheck()) return setStatus('stopped')
  setStatus('testing')
  await sleep(350)
  if (stopCheck()) return setStatus('stopped')
  const ok = Math.random() > 0.15
  push(buildDoneMessage(ok))
  session.testResult = ok
    ? { passed: 17, failed: 0, note: 'go test ./app/... + 集成用例 全部通过' }
    : { passed: 14, failed: 3, note: '集成用例存在 3 个失败，已标记风险项' }
  session.artifacts = ['app/domain.go', 'app/service.go']
  setStatus(ok ? 'done' : 'failed')
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}
