import { defineStore } from 'pinia'
import type { TestChannel, UnitTest, UnitTestSession } from '@/types'
import { unitTestService } from '@/services/unit-test-service'
import { useArchTaskStore } from './task-store'

const DEFAULT_ADAPTER_ID = 'opencode'

export const useArchUnitTestStore = defineStore('arch-unit-test', {
  state: () => ({
    tests: [] as UnitTest[],
    sessions: [] as UnitTestSession[],
    loading: false,
    loaded: false,
    activeSessionId: null as string | null,
    running: false,
    /** 默认执行通道(可在设置中调整)。 */
    defaultChannel: 'cli' as TestChannel,
  }),
  getters: {
    activeSession(state): UnitTestSession | undefined {
      return state.sessions.find((s) => s.id === state.activeSessionId)
    },
    byId(state): (id: string) => UnitTest | undefined {
      return (id: string) => state.tests.find((t) => t.id === id)
    },
    /** 被某执行任务关联的单测数量(用于任务侧角标)。 */
    linkedCount(_state): (taskId: string) => number {
      const task = useArchTaskStore()
      return (taskId: string) => task.findExecution(taskId)?.testIds?.length ?? 0
    },
    linkedTestIds(_state): (taskId: string) => string[] {
      const task = useArchTaskStore()
      return (taskId: string) => task.findExecution(taskId)?.testIds ?? []
    },
    passedCount(state): number {
      return state.tests.filter((t) => t.status === 'passed').length
    },
  },
  actions: {
    async load() {
      if (this.loaded || this.loading) return
      this.loading = true
      try {
        const [tests, sessions] = await Promise.all([unitTestService.listTests(), unitTestService.listSessions()])
        this.tests = tests
        this.sessions = sessions
      } catch {
        // 后端不可达/未重启时保持空态, 由页面引导新建
      }
      this.loaded = true
      this.loading = false
    },
    select(sessionId: string) {
      this.activeSessionId = sessionId
    },
    async createSession(opts: { title: string; channel: TestChannel; adapter?: string }) {
      const adapter = opts.adapter ?? DEFAULT_ADAPTER_ID
      const s = await unitTestService.createSession({
        title: opts.title,
        channel: opts.channel,
        adapter,
        testIds: [],
      })
      this.sessions.unshift(s)
      this.activeSessionId = s.id
      return s
    },
    /** 添加/关连测试脚本(左栏「添加」)。 */
    async addTest(data: Partial<UnitTest>) {
      const t = await unitTestService.addTest(data)
      this.tests.unshift(t)
      return t
    },
    /** 执行指定单测(单条或批量)，写入当前会话。 */
    async runTests(testIds: string[]) {
      const session = this.activeSession
      if (!session || !testIds.length || this.running) return
      const targets = this.tests.filter((t) => testIds.includes(t.id))
      this.running = true
      session.testIds = Array.from(new Set([...session.testIds, ...testIds]))
      const push = (msg: UnitTestSession['messages'][number]) => session.messages.push(msg)
      await unitTestService.runTests(session, targets, {
        onMessage: push,
        isCancelled: () => session.status === 'stopped',
      })
      if (session.status !== 'stopped') {
        const failed = this.tests.filter((t) => testIds.includes(t.id) && t.status === 'failed').length
        const passed = this.tests.filter((t) => testIds.includes(t.id) && t.status === 'passed').length
        session.messages.push({
          id: `m-${Date.now()}`, role: 'assistant', time: Date.now(),
          content: failed ? `本轮执行完成：${passed} 通过 / ${failed} 失败，可在对话中要求 agent 修复后重试。` : `本轮执行全部通过(${passed})。`,
        })
      }
      this.running = false
      session.updatedAt = Date.now()
    },
    async send(content: string) {
      const session = this.activeSession
      if (!session || !content.trim()) return
      await unitTestService.sendMessage(session, content.trim())
    },
    stop() {
      const session = this.activeSession
      if (session && session.status === 'running') session.status = 'stopped'
    },
    /** agent 辅助判定：建议某执行任务应关联的单测(mock)。 */
    suggestForTask(taskId: string): string[] {
      const task = useArchTaskStore().findExecution(taskId)
      if (!task) return []
      const pool = this.tests.filter((t) => t.status !== 'error')
      const byScope = pool
        .filter((t) => t.levels.some((l) => l === 'L0' || l === 'L1' || l === 'L2'))
        .sort((a, b) => a.levels.length - b.levels.length)
        .slice(0, 3)
      return byScope.map((t) => t.id)
    },
  },
})
