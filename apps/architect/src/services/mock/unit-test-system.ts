import type { UnitTest, UnitTestSession } from '@/types'

export const UNIT_TESTS: UnitTest[] = [
  {
    id: 'ut-1', name: '订单状态机流转测试', levels: ['L0', 'L1'], scriptPath: 'order-service/order_state_test.go',
    source: 'manual', status: 'passed',
    lastResult: { passed: 12, failed: 0, note: 'go test ./order-service -run TestOrderState', at: Date.now() - 3600000 },
    createdAt: Date.now() - 86400000 * 2, updatedAt: Date.now() - 3600000,
  },
  {
    id: 'ut-2', name: '幂等键中间件测试', levels: ['L2'], scriptPath: 'gateway/middleware/idempotency_test.go',
    source: 'manual', status: 'passed',
    lastResult: { passed: 8, failed: 0, note: 'go test ./gateway/middleware/...', at: Date.now() - 7200000 },
    createdAt: Date.now() - 86400000, updatedAt: Date.now() - 7200000,
  },
  {
    id: 'ut-3', name: 'outbox 中继投递测试', levels: ['L3'], scriptPath: 'outbox-service/relay_test.go',
    source: 'manual', status: 'failed',
    lastResult: { passed: 5, failed: 2, error: 'TestRelayRetry: 重试退避断言失败', note: 'go test ./outbox-service', at: Date.now() - 1800000 },
    createdAt: Date.now() - 86400000, updatedAt: Date.now() - 1800000,
  },
  {
    id: 'ut-4', name: '支付回调验签测试', levels: ['L4'], scriptPath: 'payment-service/callback_test.go',
    source: 'manual', status: 'idle',
    createdAt: Date.now() - 86400000 * 0.5, updatedAt: Date.now() - 86400000 * 0.5,
  },
  {
    id: 'ut-5', name: '全链路下单调试', levels: ['L5'], scriptPath: 'tests/e2e_order_flow_test.go',
    source: 'manual', status: 'idle',
    createdAt: Date.now() - 86400000 * 0.2, updatedAt: Date.now() - 86400000 * 0.2,
  },
]

export const UNIT_TEST_SESSIONS: UnitTestSession[] = [
  {
    id: 'uts-1', title: '下单链路回归', channel: 'cli', adapter: 'opencode', testIds: ['ut-1', 'ut-2'],
    status: 'done',
    messages: [
      { id: 'm1', role: 'user', time: Date.now() - 7200000, content: '执行已关联单测：订单状态机 + 幂等键中间件' },
      { id: 'm2', role: 'tool', time: Date.now() - 7190000, tool: { type: 'run-test', label: 'go test ./order-service -run TestOrderState', detail: '12 通过 / 0 失败', ok: true }, content: '' },
      { id: 'm3', role: 'tool', time: Date.now() - 7180000, tool: { type: 'run-test', label: 'go test ./gateway/middleware/...', detail: '8 通过 / 0 失败', ok: true }, content: '' },
      { id: 'm4', role: 'assistant', time: Date.now() - 7170000, content: '两例全部通过，验收清单关联项满足。' },
    ],
    stats: { requests: 6, tokensIn: 8400, tokensOut: 3100, bytesIn: 21000, bytesOut: 9000 },
    createdAt: Date.now() - 7200000, updatedAt: Date.now() - 7170000,
  },
]
