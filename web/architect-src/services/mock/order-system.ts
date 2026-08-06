import type {
  AgentSession, AppendedReq, ArchComponent, ArchitectureSpec, CodeMapping, ComplianceCheck, DataFlow,
  DesignPlan, EntityClass, ErTable, ExecutionFlow, ExecutionTask, ExternalCall, IncrementalLogEntry, OrmMapping, ProjectInfo, RepoStatus, Requirement, Snapshot, StagingModel, TaskNode, UserInteraction,
} from '@/types'

export const BASELINE_COMMIT = '1a2b3c4d5e6f'

export const AGENT_ADAPTERS = [
  { id: 'opencode', name: 'opencode', keepContext: true, note: '会话保持 · 支持多轮上下文延续', models: ['default', 'fast', 'large'] },
  { id: 'codex', name: 'codex', keepContext: true, note: '会话保持 · CLI 批量执行', models: ['default', 'max-effort'] },
  { id: 'claude-code', name: 'claude-code', keepContext: true, note: '会话保持 · 长上下文', models: ['opus', 'sonnet', 'haiku'] },
]

export const PROJECT_INFO: ProjectInfo = {
  id: 'proj-order',
  name: '订单服务系统',
  desc: '需求驱动 + 架构驱动示例：下单 → 库存预扣 → 支付 → 事件最终一致 → 超时关单',
  rootPath: '/home/dev/topo-projects/order-service',
  kbRoot: '/home/dev/topo-storage/worktrees/baseline',
  branch: 'main',
  baselineId: 'baseline_id = N',
  baselineCommit: BASELINE_COMMIT,
  createdAt: Date.now() - 86400000 * 3,
  active: true,
  config: {
    estMinMin: 60,
    estMinMax: 480,
    acceptanceMax: 4,
    p0SubsetMax: 5,
  },
  mode: 'existing',
  productForm: 'io',
}

export const GREENFIELD_PROJECT: ProjectInfo = {
  id: 'proj-green',
  name: '新项目',
  desc: '从零开始的 greenfield 项目',
  rootPath: '',
  kbRoot: '',
  branch: 'main',
  baselineId: null,
  baselineCommit: '',
  createdAt: Date.now(),
  active: true,
  config: {
    estMinMin: 15,
    estMinMax: 240,
    acceptanceMax: 6,
    p0SubsetMax: 4,
  },
  mode: 'greenfield',
  scaffold: { language: '', moduleLayout: 'mono' },
}

export const REPO_STATUS: RepoStatus = {
  baseline: {
    id: 'baseline_id = N',
    version: 'v0.0.1',
    commit: BASELINE_COMMIT,
    manifestHash: 'sha256:9f7…c21',
    createdAt: Date.now() - 86400000 * 3,
  },
  head: {
    commit: 'a1b2c3d4e5f6',
    branch: 'main',
    ahead: 6,
  },
  diff: {
    filesChanged: 5,
    added: 2,
    modified: 3,
    deleted: 0,
    deletedHighRisk: false,
    files: ['order-service/order.go', 'order-service/service.go', 'order-service/close.go', 'outbox-service/relay.go', 'tests/integration_test.go'],
  },
  lastRebaseline: null,
}

export const REQUIREMENTS: Requirement[] = [
  {
    id: 'RQ-1', kind: 'user-story', tier: 'raw', title: '用户下单全链路', priority: 'P0', status: 'raw',
    desc: '用户浏览商品后可提交订单，系统校验商品可售性、创建待支付订单，支持支付与库存扣减，直至最终完成。',
    acceptance: ['端到端下单链路可用'], traceTo: ['order-service', 'inventory-service', 'payment-service'],
    updatedAt: Date.now() - 86400000 * 6,
  },
  {
    id: 'RQ-2', kind: 'fr', tier: 'raw', title: '可靠事件投递', priority: 'P1', status: 'raw',
    desc: '订单领域事件需要可靠投递到消息中间件，保证不丢不重。',
    acceptance: ['事件不丢不重'], traceTo: ['order-service', 'outbox-service'],
    updatedAt: Date.now() - 86400000 * 5,
  },
  {
    id: 'RQ-3', kind: 'nfr', tier: 'raw', title: '可观测性', priority: 'P2', status: 'raw',
    desc: '核心链路输出 trace 与业务指标，支撑排障与容量评估。',
    acceptance: ['关键链路可观测'], traceTo: ['order-service'],
    updatedAt: Date.now() - 86400000 * 5,
  },
  {
    id: 'RQ-4', kind: 'nfr', tier: 'raw', title: '可用性保障', priority: 'P1', status: 'raw',
    desc: '核心链路故障可降级，支付渠道故障不阻塞主流程。',
    acceptance: ['故障可降级'], traceTo: ['gateway', 'payment-service'],
    updatedAt: Date.now() - 86400000 * 4,
  },
  {
    id: 'US-1', kind: 'user-story', tier: 'analyzed', title: '下单主链路', priority: 'P0', status: 'analyzed',
    desc: '用户提交订单，系统创建待支付订单并返回单号，同事务写入 outbox 事件。',
    acceptance: ['创建订单后进入「待支付」状态', '订单号唯一可追溯', '事件入库与业务同事务'],
    traceTo: ['order-service'],
    parentId: 'RQ-1',
    planId: 'plan-1',
    routedBy: 'analysis',
    analysis: {
      functionalScope: ['提交订单', '订单状态机初始化', '领域事件本地落库'],
      entityBoundary: ['Order', 'OrderItem', 'OutboxEvent'],
      feasibility: { ok: true, reason: '已有订单基础结构，改动集中在状态机扩展', estMin: 240 },
      specsMd: '事件写入与业务变更必须在同一数据库事务(本地 outbox)\n幂等键取自请求头 Idempotency-Key',
      assetScope: [
        { assetId: 'c-order', assetType: 'component', role: 'core', source: 'auto' },
        { assetId: 'entity-order', assetType: 'entity', role: 'core', source: 'auto' },
        { assetId: 'er-order', assetType: 'er', role: 'core', source: 'auto' },
        { assetId: 'flow-place-order', assetType: 'flow', role: 'core', source: 'auto' },
        { assetId: 'c-gateway', assetType: 'component', role: 'related', source: 'auto' },
      ],
    },
    updatedAt: Date.now() - 86400000 * 2,
  },
  {
    id: 'US-2', kind: 'user-story', tier: 'analyzed', title: '用户支付', priority: 'P0', status: 'analyzed',
    desc: '用户对待支付订单发起支付，支付结果通过回调异步通知，成功后订单流转为已支付。',
    acceptance: ['支付成功后订单流转为「已支付」', '支付回调不丢、不重'],
    traceTo: ['payment-service', 'order-service'],
    parentId: 'RQ-1',
    analysis: {
      functionalScope: ['创建支付单', '渠道适配调用', '回调验签与去重'],
      entityBoundary: ['Payment', 'PaymentGatewayRef'],
      feasibility: { ok: true, reason: '支付单模型已存在，补充渠道适配层', estMin: 300 },
      assetScope: [
        { assetId: 'c-payment', assetType: 'component', role: 'core', source: 'auto' },
        { assetId: 'entity-payment', assetType: 'entity', role: 'core', source: 'auto' },
        { assetId: 'er-payment', assetType: 'er', role: 'related', source: 'auto' },
        { assetId: 'df-pay-cb', assetType: 'dataflow', role: 'related', source: 'auto' },
      ],
    },
    updatedAt: Date.now() - 86400000 * 2,
  },
  {
    id: 'US-3', kind: 'user-story', tier: 'analyzed', title: '库存扣减', priority: 'P0', status: 'analyzed',
    desc: '下单时预占库存，支付成功后才实际扣减，取消/关闭订单释放预占库存。',
    acceptance: ['下单预扣库存不超卖', '支付成功完成实扣', '关单后库存回补'],
    traceTo: ['inventory-service'],
    parentId: 'RQ-1',
    analysis: {
      functionalScope: ['库存预占', '支付实扣', '关单回补'],
      entityBoundary: ['Inventory'],
      feasibility: { ok: true, reason: '不超卖约束已定义，按状态机补齐预占/实扣/回补', estMin: 240 },
      assetScope: [
        { assetId: 'c-inventory', assetType: 'component', role: 'core', source: 'auto' },
        { assetId: 'entity-inventory', assetType: 'entity', role: 'core', source: 'auto' },
      ],
    },
    updatedAt: Date.now() - 86400000 * 2,
  },
  {
    id: 'FR-1', kind: 'fr', tier: 'analyzed', title: '下单幂等', priority: 'P0', status: 'analyzed',
    desc: '同一业务请求(幂等键)重复到达时只处理一次，幂等键由网关生成并透传。',
    acceptance: ['相同幂等键返回相同订单', '幂等校验通过唯一约束实现'],
    traceTo: ['order-service'],
    parentId: 'RQ-1',
    planId: 'plan-1',
    analysis: {
      functionalScope: ['幂等键生成', '幂等键透传', '唯一约束冲突处理'],
      entityBoundary: ['Order(idempotency_key)'],
      feasibility: { ok: true, reason: '唯一约束方案明确，改动面小', estMin: 120 },
      assetScope: [
        { assetId: 'c-gateway', assetType: 'component', role: 'core', source: 'auto' },
        { assetId: 'c-order', assetType: 'component', role: 'core', source: 'auto' },
        { assetId: 'entity-order', assetType: 'entity', role: 'related', source: 'auto' },
      ],
    },
    updatedAt: Date.now() - 3600000 * 6,
  },
  {
    id: 'FR-2', kind: 'fr', tier: 'analyzed', title: '事件不丢不重', priority: 'P1', status: 'analyzed',
    desc: '订单领域事件通过本地 outbox + 可靠中继投递，保证最终一致且不重复消费。',
    acceptance: ['事件入库与业务操作同事务', '消费侧按事件ID去重', '中继失败进入死信并告警'],
    traceTo: ['outbox-service', 'rabbitmq'],
    parentId: 'RQ-2',
    planId: 'plan-2',
    analysis: {
      functionalScope: ['outbox 中继组件', '事件去重消费', '死信与告警'],
      entityBoundary: ['OutboxEvent'],
      feasibility: { ok: true, reason: '本地消息表模式，无新增外部依赖', estMin: 420 },
      assetScope: [
        { assetId: 'c-outbox', assetType: 'component', role: 'core', source: 'auto' },
        { assetId: 'entity-outbox', assetType: 'entity', role: 'core', source: 'auto' },
        { assetId: 'er-outbox', assetType: 'er', role: 'core', source: 'auto' },
        { assetId: 'c-order', assetType: 'component', role: 'related', source: 'auto' },
        { assetId: 'c-mq', assetType: 'component', role: 'related', source: 'auto' },
      ],
    },
    updatedAt: Date.now() - 3600000 * 4,
  },
  {
    id: 'NFR-1', kind: 'nfr', tier: 'analyzed', title: '可用性 ≥ 99.9%', priority: 'P1', status: 'analyzed',
    desc: '核心链路故障可降级，支付渠道故障不阻塞主流程。',
    acceptance: ['支付渠道超时自动重试并最终关闭订单', '读多写少场景支持缓存降级'],
    traceTo: ['gateway', 'payment-service'],
    parentId: 'RQ-4',
    planId: 'plan-2',
    analysis: {
      functionalScope: ['缓存降级', '支付超时关单'],
      entityBoundary: ['Order(status)', 'Payment(status)'],
      feasibility: { ok: true, reason: '超时关单已有流程，缓存降级为网关侧改造', estMin: 240 },
      assetScope: [
        { assetId: 'c-gateway', assetType: 'component', role: 'core', source: 'auto' },
        { assetId: 'flow-timeout-close', assetType: 'flow', role: 'related', source: 'auto' },
      ],
    },
    updatedAt: Date.now() - 3600000 * 2,
  },
  {
    id: 'NFR-2', kind: 'nfr', tier: 'analyzed', title: '可观测性', priority: 'P2', status: 'analyzed',
    desc: '核心链路输出 trace、业务指标(下单量/支付成功率/库存预占水位)。',
    acceptance: ['关键方法带 trace span', '下单/支付/关单均有业务指标'],
    traceTo: ['order-service'],
    parentId: 'RQ-3',
    analysis: {
      functionalScope: ['trace 埋点', '业务指标采集', '指标面板聚合'],
      entityBoundary: ['OrderMetrics'],
      feasibility: { ok: false, reason: '指标面板依赖运维侧 Grafana，需先确认接入渠道', estMin: 520 },
      assetScope: [
        { assetId: 'c-order', assetType: 'component', role: 'core', source: 'auto' },
      ],
    },
    updatedAt: Date.now() - 86400000 * 5,
  },
]

export const PLANS: DesignPlan[] = [
  {
    id: 'plan-1', reqIds: ['US-1', 'FR-1'],
    title: '下单主链路 + 幂等加固',
    approach: '在 order-service 内扩展现有订单状态机：同事务写入本地 outbox 事件，网关生成幂等键透传并落到 idempotency_key 唯一约束；改动集中在订单核心与网关中间件，不新增外部服务。',
    changes: [
      { resource: 'order-service', kind: 'modified', before: '订单创建流程，无幂等校验，事件经同步 RPC', after: '幂等查重 + 同事务写 outbox(OrderCreated)' },
      { resource: 'Order', kind: 'modified', before: '无 idempotency_key / version', after: '新增 idempotency_key(unique) + version(乐观锁)' },
      { resource: 'api-gateway', kind: 'modified', before: '仅鉴权/限流', after: '幂等键生成与透传中间件' },
      { resource: 'flow-place-order', kind: 'modified', before: '6 步，无幂等/事件节点', after: '插入幂等校验 + 事件落库节点' },
      { resource: 'outbox-service', kind: 'added', before: '不存在', after: '新增中继组件(轮询投递/死信)' },
    ],
    impact: {
      affected: ['order-service', 'api-gateway', 'outbox-service', 'inventory-service'],
      grade: 'M',
      basis: '修改 3 组件 + 新增 1 组件，触及枢纽 order-service，无删除',
      risks: ['幂等键灰度需 5% 流量验证', 'outbox 中继需处理投递失败重试'],
    },
    status: 'confirmed',
    taskPlanId: 'tp-1',
    baseCommit: '1a2b3c4d5e6f',
    updatedAt: Date.now() - 3600000 * 3,
  },
  {
    id: 'plan-2', reqIds: ['FR-2', 'NFR-1'],
    title: '可靠事件 + 可用性保障',
    approach: '以本地 outbox + 可靠中继承载领域事件，支付渠道超时自动重试并最终关单，网关侧引入缓存降级。',
    changes: [
      { resource: 'outbox-service', kind: 'added', before: '不存在', after: '中继组件 + 死信告警' },
      { resource: 'payment-service', kind: 'modified', before: '回调无去重', after: '回调验签 + event_id 去重' },
      { resource: 'api-gateway', kind: 'modified', before: '无缓存层', after: '读路径缓存降级' },
      { resource: 'flow-timeout-close', kind: 'modified', before: '无重试策略', after: '支付超时重试 + 关单释放库存' },
    ],
    impact: {
      affected: ['outbox-service', 'payment-service', 'api-gateway'],
      grade: 'S',
      basis: '范围可控，新增 1 组件，无核心文件改动',
      risks: ['事件顺序性: 单 key 有序 + event_id 去重'],
    },
    status: 'confirmed',
    taskPlanId: 'tp-2',
    baseCommit: '1a2b3c4d5e6f',
    updatedAt: Date.now() - 3600000 * 1,
  },
  {
    id: 'plan-3', reqIds: ['US-2', 'US-3'],
    title: '支付与库存扣减',
    approach: '支付渠道适配层接入 + 库存预占/实扣/回补状态机补齐。',
    changes: [
      { resource: 'payment-service', kind: 'modified', before: '固定渠道', after: '适配层 DTO 屏蔽渠道差异' },
      { resource: 'inventory-service', kind: 'modified', before: '仅预扣', after: '预占/实扣/回补完整状态机' },
    ],
    impact: {
      affected: ['payment-service', 'inventory-service'],
      grade: 'S',
      basis: '改动集中在两个服务内部',
      risks: ['库存不超卖约束需回归验证'],
    },
    status: 'draft',
    baseCommit: '1a2b3c4d5e6f',
    updatedAt: Date.now() - 3600000,
  },
]

export const PLAN_TASK_TREES: Record<string, TaskNode> = {
  'tp-1': {
    id: 'tp-1', title: '下单主链路 + 幂等加固(任务方案)', kind: 'epic', status: 'in-progress', estMin: 360,
    context: ['方案: plan-1', '需求: US-1/FR-1', '设计: flow-place-order / Order 结构'],
    files: ['order-service/', 'gateway/'],
    children: [
      { id: 'tp-1/a', title: '网关幂等键中间件', kind: 'task', status: 'done', estMin: 60, context: ['FR-1'], files: ['gateway/middleware/idempotency.go'] },
      { id: 'tp-1/b', title: '订单核心下单 + 事件落库', kind: 'task', status: 'in-progress', estMin: 180, context: ['US-1', 'FR-1', 'Order 状态机'], files: ['order-service/order.go'] },
      { id: 'tp-1/c', title: 'outbox 中继接入', kind: 'task', status: 'pending', estMin: 120, context: ['US-1', 'OutboxEvent'], files: ['outbox-service/relay.go'] },
    ],
  },
  'tp-2': {
    id: 'tp-2', title: '可靠事件 + 可用性保障(任务方案)', kind: 'epic', status: 'pending', estMin: 420,
    context: ['方案: plan-2', '需求: FR-2/NFR-1', '设计: 缓存降级 / 超时关单'],
    files: ['outbox-service/', 'payment-service/', 'gateway/'],
    children: [
      { id: 'tp-2/a', title: 'outbox 中继 + 死信告警', kind: 'task', status: 'pending', estMin: 240, context: ['FR-2'], files: ['outbox-service/relay.go'] },
      { id: 'tp-2/b', title: '回调验签去重', kind: 'task', status: 'pending', estMin: 60, context: ['FR-2'], files: ['payment-service/callback.go'] },
      { id: 'tp-2/c', title: '缓存降级', kind: 'task', status: 'pending', estMin: 120, context: ['NFR-1'], files: ['gateway/cache.go'] },
    ],
  },
}

export const EXECUTION_TASKS: ExecutionTask[] = [
  {
    id: 'ex-1', planId: 'plan-1', adapter: 'opencode', model: 'default',
    reqIds: ['RQ-1'],
    connectivity: 'ok', status: 'running',
    sessionIds: ['sess-ex-1'],
    baseCommit: '1a2b3c4d5e6f', runCount: 1,
    testIds: ['ut-1', 'ut-2'],
    createdAt: Date.now() - 3600000,
    updatedAt: Date.now() - 60000,
    stats: { requests: 8, tokensIn: 12400, tokensOut: 5200, bytesIn: 48200, bytesOut: 21000 },
    amendments: [
      {
        id: 'ap-1', title: '下单成功后返回优惠信息', desc: '支付前需要展示当前可享优惠，联动用户等级。',
        scope: ['order-service', 'user-profile'],
        status: 'designed', updatedAt: Date.now() - 1200000,
        analysis: {
          functionalScope: ['优惠试算', '优惠展示'],
          entityBoundary: ['OrderDiscount'],
          feasibility: { ok: true, reason: '优惠规则为只读查询，可在订单详情接口追加字段', estMin: 90 },
          assetScope: [{ assetId: 'c-order', assetType: 'component', role: 'core', source: 'auto' }],
        },
        design: {
          approach: '在订单详情返回中追加优惠字段，网关侧缓存用户等级映射。',
          changes: [{ resource: 'order-service', kind: 'modified', before: '订单详情无优惠信息', after: '追加优惠试算结果字段' }],
        },
      },
    ],
  },
  {
    id: 'ex-2', planId: 'plan-2', adapter: 'codex', model: 'default',
    reqIds: ['RQ-2'],
    connectivity: 'unknown', status: 'created',
    sessionIds: [],
    baseCommit: '1a2b3c4d5e6f', runCount: 1,
    createdAt: Date.now() - 1800000,
    updatedAt: Date.now() - 1800000,
    amendments: [],
  },
  {
    id: 'ex-3', planId: 'plan-3', adapter: 'claude-code', model: 'sonnet',
    reqIds: ['RQ-3'],
    connectivity: 'ok', status: 'done',
    sessionIds: ['sess-ex-3'],
    baseCommit: '1a2b3c4d5e6f', runCount: 2,
    testIds: ['ut-3'],
    createdAt: Date.now() - 86400000,
    updatedAt: Date.now() - 7200000,
    endedAt: Date.now() - 7200000,
    stats: { requests: 23, tokensIn: 31200, tokensOut: 14800, bytesIn: 112000, bytesOut: 59000 },
    amendments: [],
  },
]

export const APPENDED_REQS: AppendedReq[] = [
  {
    id: 'ap-1', title: '下单成功后返回优惠信息', desc: '支付前需要展示当前可享优惠，联动用户等级。',
    scope: ['order-service', 'user-profile'],
    status: 'designed', updatedAt: Date.now() - 1200000,
    analysis: {
      functionalScope: ['优惠试算', '优惠展示'],
      entityBoundary: ['OrderDiscount'],
      feasibility: { ok: true, reason: '优惠规则为只读查询，可在订单详情接口追加字段', estMin: 90 },
      assetScope: [{ assetId: 'c-order', assetType: 'component', role: 'core', source: 'auto' }],
    },
    design: {
      approach: '在订单详情返回中追加优惠字段，网关侧缓存用户等级映射。',
      changes: [{ resource: 'order-service', kind: 'modified', before: '订单详情无优惠信息', after: '追加优惠试算结果字段' }],
    },
  },
]

function baseComponents(): ArchComponent[] {
  return [
    {
      id: 'c-gateway', name: 'api-gateway', kind: 'gateway', lang: 'Go', change: 'same',
      desc: '统一入口，负责鉴权、限流、幂等键生成与路由分发。',
      responsibilities: ['请求鉴权', '幂等键生成(Idempotency-Key)', '限流与熔断'],
      owns: [], dependsOn: ['c-order', 'c-payment'],
    },
    {
      id: 'c-order', name: 'order-service', kind: 'service', lang: 'Go', change: 'modified',
      desc: '订单领域核心，维护订单状态机并发布领域事件。',
      responsibilities: ['下单/状态流转', '幂等校验', '领域事件写入 outbox'],
      parentId: 'c-gateway', owns: ['entity-order', 'er-order', 'orm-order'], dependsOn: ['c-inventory', 'c-payment', 'c-mysql', 'c-mq'],
    },
    {
      id: 'c-inventory', name: 'inventory-service', kind: 'service', lang: 'Java', change: 'same',
      desc: '库存预占/实扣/回补，保证不超卖。',
      responsibilities: ['预扣库存', '实扣库存', '释放库存'],
      parentId: 'c-order', owns: ['entity-inventory', 'er-inventory'], dependsOn: ['c-mysql'],
    },
    {
      id: 'c-payment', name: 'payment-service', kind: 'service', lang: 'Java', change: 'modified',
      desc: '支付渠道适配与回调处理，通过支付网关适配层对接第三方渠道。',
      responsibilities: ['创建支付单', '渠道调用(适配层)', '回调验签与去重'],
      parentId: 'c-order', owns: ['entity-payment', 'er-payment', 'orm-payment'], dependsOn: ['c-mysql', 'c-mq'],
    },
    {
      id: 'c-outbox', name: 'outbox-service', kind: 'service', lang: 'Go', change: 'added',
      desc: '本地消息表的中继组件，将 outbox 中的领域事件可靠投递到 MQ。',
      responsibilities: ['轮询未投递事件', '投递 + 确认回执', '重试与死信'],
      parentId: 'c-order', owns: ['entity-outbox', 'er-outbox', 'orm-outbox'], dependsOn: ['c-mysql', 'c-mq'],
    },
    {
      id: 'c-mysql', name: 'mysql-cluster', kind: 'storage', lang: '-', change: 'same',
      desc: '业务主存储，分库分表承载各服务数据。',
      responsibilities: ['持久化', '唯一约束(幂等)', '事务'],
      owns: [], dependsOn: [],
    },
    {
      id: 'c-mq', name: 'rabbitmq', kind: 'infra', lang: '-', change: 'same',
      desc: '消息中间件，承载领域事件与回调事件。',
      responsibilities: ['事件投递', '死信队列'],
      owns: [], dependsOn: [],
    },
  ]
}

function baseErTables(): ErTable[] {
  return [
    {
      id: 'er-order', name: 'orders', level: 'physical', change: 'modified',
      desc: '订单主表，随事件溯源引入状态机与幂等键。',
      columns: [
        { name: 'order_no', type: 'string(32)', nullable: false, pk: true, desc: '业务单号', ast: { file: 'order-service/order.go', symbol: 'Order.OrderNo', kind: 'column', startLine: 3, endLine: 3 } },
        { name: 'idempotency_key', type: 'string(64)', nullable: false, desc: '幂等键(网关生成)', ast: { file: 'order-service/order.go', symbol: 'Order.IdempotencyKey', kind: 'column', startLine: 4, endLine: 4 } },
        { name: 'user_id', type: 'bigint', nullable: false, desc: '下单用户', ast: { file: 'order-service/order.go', symbol: 'Order.UserId', kind: 'column', startLine: 5, endLine: 5 } },
        { name: 'status', type: 'enum', nullable: false, desc: '待支付/已支付/已关闭/已完成', ast: { file: 'order-service/order.go', symbol: 'Order.Status', kind: 'column', startLine: 6, endLine: 6 } },
        { name: 'amount', type: 'decimal(12,2)', nullable: false, desc: '订单金额', ast: { file: 'order-service/order.go', symbol: 'Order.Amount', kind: 'column', startLine: 7, endLine: 7 } },
        { name: 'version', type: 'int', nullable: false, desc: '乐观锁版本', ast: { file: 'order-service/order.go', symbol: 'Order.Version', kind: 'column', startLine: 8, endLine: 8 } },
        { name: 'created_at', type: 'datetime', nullable: false, desc: '创建时间', ast: { file: 'order-service/order.go', symbol: 'Order.CreatedAt', kind: 'column', startLine: 9, endLine: 9 } },
        { name: 'closed_at', type: 'datetime', nullable: true, desc: '关闭时间', ast: { file: 'order-service/order.go', symbol: 'Order.ClosedAt', kind: 'column', startLine: 10, endLine: 10 } },
      ],
      relations: [
        { from: 'er-order', to: 'er-order-item', type: '1:N', key: 'order_no' },
        { from: 'er-order', to: 'er-payment', type: '1:1', key: 'order_no' },
      ],
      invariants: ['status 变迁仅沿: 待支付→已支付→已完成 / 待支付→已关闭', '订单总额 = Σ(order_item.amount)'],
      ast: { file: 'order-service/order.go', symbol: 'Order', kind: 'table', startLine: 3, endLine: 11 },
    },
    {
      id: 'er-order-item', name: 'order_item', level: 'physical', change: 'same',
      desc: '订单明细表。',
      columns: [
        { name: 'id', type: 'bigint', nullable: false, pk: true, desc: '主键', ast: { file: 'order-service/order.go', symbol: 'OrderItem.Id', kind: 'column', startLine: 3, endLine: 3 } },
        { name: 'order_no', type: 'string(32)', nullable: false, fk: 'er-order', desc: '归属订单', ast: { file: 'order-service/order.go', symbol: 'OrderItem.OrderNo', kind: 'column', startLine: 4, endLine: 4 } },
        { name: 'sku_id', type: 'bigint', nullable: false, desc: 'SKU', ast: { file: 'order-service/order.go', symbol: 'OrderItem.SkuId', kind: 'column', startLine: 5, endLine: 5 } },
        { name: 'quantity', type: 'int', nullable: false, desc: '数量', ast: { file: 'order-service/order.go', symbol: 'OrderItem.Quantity', kind: 'column', startLine: 6, endLine: 6 } },
        { name: 'amount', type: 'decimal(12,2)', nullable: false, desc: '行金额', ast: { file: 'order-service/order.go', symbol: 'OrderItem.Amount', kind: 'column', startLine: 7, endLine: 7 } },
      ],
      relations: [],
      invariants: [],
      ast: { file: 'order-service/order.go', symbol: 'OrderItem', kind: 'table', startLine: 12, endLine: 19 },
    },
    {
      id: 'er-payment', name: 'payment', level: 'physical', change: 'same',
      desc: '支付单表，与订单 1:1。',
      columns: [
        { name: 'id', type: 'bigint', nullable: false, pk: true, desc: '主键', ast: { file: 'payment-service/pay.go', symbol: 'Payment.Id', kind: 'column', startLine: 3, endLine: 3 } },
        { name: 'order_no', type: 'string(32)', nullable: false, fk: 'er-order', desc: '订单号', ast: { file: 'payment-service/pay.go', symbol: 'Payment.OrderNo', kind: 'column', startLine: 4, endLine: 4 } },
        { name: 'channel', type: 'string(32)', nullable: false, desc: '支付渠道', ast: { file: 'payment-service/pay.go', symbol: 'Payment.Channel', kind: 'column', startLine: 5, endLine: 5 } },
        { name: 'status', type: 'enum', nullable: false, desc: '待支付/成功/失败', ast: { file: 'payment-service/pay.go', symbol: 'Payment.Status', kind: 'column', startLine: 6, endLine: 6 } },
        { name: 'paid_at', type: 'datetime', nullable: true, desc: '支付时间', ast: { file: 'payment-service/pay.go', symbol: 'Payment.PaidAt', kind: 'column', startLine: 7, endLine: 7 } },
      ],
      relations: [],
      invariants: ['一个订单仅能存在一个成功支付单'],
      ast: { file: 'payment-service/pay.go', symbol: 'Payment', kind: 'table', startLine: 3, endLine: 9 },
    },
    {
      id: 'er-inventory', name: 'inventory', level: 'physical', change: 'same',
      desc: '库存快照 + 预占水位。',
      columns: [
        { name: 'sku_id', type: 'bigint', nullable: false, pk: true, desc: 'SKU', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.SkuId', kind: 'column', startLine: 3, endLine: 3 } },
        { name: 'available', type: 'int', nullable: false, desc: '可售库存', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.Available', kind: 'column', startLine: 4, endLine: 4 } },
        { name: 'reserved', type: 'int', nullable: false, desc: '已预占', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.Reserved', kind: 'column', startLine: 5, endLine: 5 } },
      ],
      relations: [],
      invariants: ['available >= 0(不超卖)', '实扣后 reserved 回落'],
      ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory', kind: 'table', startLine: 3, endLine: 6 },
    },
    {
      id: 'er-outbox', name: 'outbox_event', level: 'physical', change: 'added',
      desc: '本地消息表(事件溯源)，与业务操作同事务写入。',
      columns: [
        { name: 'id', type: 'bigint', nullable: false, pk: true, desc: '主键', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.Id', kind: 'column', startLine: 8, endLine: 8 } },
        { name: 'event_id', type: 'string(64)', nullable: false, desc: '事件ID(消费方去重)', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.EventId', kind: 'column', startLine: 9, endLine: 9 } },
        { name: 'type', type: 'string(64)', nullable: false, desc: '事件类型(OrderCreated…)', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.Type', kind: 'column', startLine: 10, endLine: 10 } },
        { name: 'payload', type: 'json', nullable: false, desc: '事件体', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.Payload', kind: 'column', startLine: 11, endLine: 11 } },
        { name: 'status', type: 'enum', nullable: false, desc: 'pending/sent/dead', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.Status', kind: 'column', startLine: 12, endLine: 12 } },
      ],
      relations: [],
      invariants: ['事件写入与订单更新处于同一数据库事务'],
      ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent', kind: 'table', startLine: 8, endLine: 14 },
    },
  ]
}

function baseOrmMappings(): OrmMapping[] {
  return [
    {
      id: 'orm-order', name: 'OrderEntity ↔ orders', entity: 'Order', table: 'orders', level: 'physical', change: 'modified',
      desc: '订单实体到主表的一对一映射；v1 新增 idempotency_key / version 字段映射。',
      fields: [
        { entityField: 'OrderNo', column: 'order_no', type: 'string', tag: 'gorm:"primaryKey"', desc: '业务单号', ast: { file: 'order-service/order.go', symbol: 'Order.OrderNo', kind: 'mapping', startLine: 3, endLine: 3 } },
        { entityField: 'IdempotencyKey', column: 'idempotency_key', type: 'string', tag: 'gorm:"uniqueIndex"', desc: '幂等键', ast: { file: 'order-service/order.go', symbol: 'Order.IdempotencyKey', kind: 'mapping', startLine: 4, endLine: 4 } },
        { entityField: 'Status', column: 'status', type: 'OrderStatus', tag: 'gorm:"type:enum"', desc: '状态机', ast: { file: 'order-service/order.go', symbol: 'Order.Status', kind: 'mapping', startLine: 6, endLine: 6 } },
        { entityField: 'Version', column: 'version', type: 'int', tag: 'gorm:"version"', desc: '乐观锁', ast: { file: 'order-service/order.go', symbol: 'Order.Version', kind: 'mapping', startLine: 8, endLine: 8 } },
      ],
      ast: { file: 'order-service/order.go', symbol: 'Order', kind: 'mapping', startLine: 3, endLine: 11 },
    },
    {
      id: 'orm-payment', name: 'PaymentEntity ↔ payment', entity: 'Payment', table: 'payment', level: 'physical', change: 'same',
      desc: '支付单实体映射。',
      fields: [
        { entityField: 'OrderNo', column: 'order_no', type: 'string', tag: 'gorm:"uniqueIndex"', desc: '订单号', ast: { file: 'payment-service/pay.go', symbol: 'Payment.OrderNo', kind: 'mapping', startLine: 4, endLine: 4 } },
        { entityField: 'Channel', column: 'channel', type: 'string', tag: '', desc: '支付渠道', ast: { file: 'payment-service/pay.go', symbol: 'Payment.Channel', kind: 'mapping', startLine: 5, endLine: 5 } },
      ],
      ast: { file: 'payment-service/pay.go', symbol: 'Payment', kind: 'mapping', startLine: 3, endLine: 9 },
    },
    {
      id: 'orm-outbox', name: 'OutboxEntity ↔ outbox_event', entity: 'OutboxEvent', table: 'outbox_event', level: 'physical', change: 'added',
      desc: '本地消息表实体映射(同事务写入)。',
      fields: [
        { entityField: 'EventId', column: 'event_id', type: 'string', tag: 'gorm:"uniqueIndex"', desc: '事件ID', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.EventId', kind: 'mapping', startLine: 9, endLine: 9 } },
        { entityField: 'Type', column: 'type', type: 'string', tag: '', desc: '事件类型', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.Type', kind: 'mapping', startLine: 10, endLine: 10 } },
        { entityField: 'Status', column: 'status', type: 'OutboxStatus', tag: 'gorm:"type:enum"', desc: '投递状态', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.Status', kind: 'mapping', startLine: 12, endLine: 12 } },
      ],
      ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent', kind: 'mapping', startLine: 8, endLine: 14 },
    },
  ]
}

function baseEntityClasses(): EntityClass[] {
  return [
    {
      id: 'entity-order', name: 'Order', kind: 'struct', level: 'physical', change: 'modified',
      desc: '订单领域聚合根，随事件溯源引入状态机与幂等键。',
      fields: [
        { name: 'OrderNo', type: 'string', visibility: 'public', desc: '业务单号', ast: { file: 'order-service/order.go', symbol: 'Order.OrderNo', kind: 'field', startLine: 3, endLine: 3 } },
        { name: 'IdempotencyKey', type: 'string', visibility: 'private', desc: '幂等键(网关生成)', ast: { file: 'order-service/order.go', symbol: 'Order.IdempotencyKey', kind: 'field', startLine: 4, endLine: 4 } },
        { name: 'Status', type: 'OrderStatus', visibility: 'private', desc: '订单状态机', ast: { file: 'order-service/order.go', symbol: 'Order.Status', kind: 'field', startLine: 6, endLine: 6 } },
        { name: 'Amount', type: 'Decimal', visibility: 'public', desc: '订单金额', ast: { file: 'order-service/order.go', symbol: 'Order.Amount', kind: 'field', startLine: 7, endLine: 7 } },
      ],
      methods: [
        { name: 'transition', signature: 'transition(next OrderStatus)', returnType: 'error', desc: '状态机统一变迁入口，禁止旁路修改', ast: { file: 'order-service/order.go', symbol: 'Order.transition', kind: 'method', startLine: 20, endLine: 35 } },
        { name: 'Create', signature: 'Create(cmd CreateOrderCmd)', returnType: '(*Order, error)', desc: '下单聚合工厂，同事务写 outbox', ast: { file: 'order-service/order.go', symbol: 'CreateOrder', kind: 'func', startLine: 40, endLine: 66 } },
      ],
      ast: { file: 'order-service/order.go', symbol: 'Order', kind: 'struct', startLine: 3, endLine: 12 },
    },
    {
      id: 'entity-payment', name: 'Payment', kind: 'struct', level: 'physical', change: 'same',
      desc: '支付单实体，与订单 1:1。',
      fields: [
        { name: 'OrderNo', type: 'string', visibility: 'public', desc: '订单号', ast: { file: 'payment-service/pay.go', symbol: 'Payment.OrderNo', kind: 'field', startLine: 4, endLine: 4 } },
        { name: 'Channel', type: 'string', visibility: 'public', desc: '支付渠道', ast: { file: 'payment-service/pay.go', symbol: 'Payment.Channel', kind: 'field', startLine: 5, endLine: 5 } },
      ],
      methods: [
        { name: 'Paid', signature: 'Paid()', returnType: 'error', desc: '标记支付成功', ast: { file: 'payment-service/pay.go', symbol: 'Payment.Paid', kind: 'method', startLine: 12, endLine: 20 } },
      ],
      ast: { file: 'payment-service/pay.go', symbol: 'Payment', kind: 'struct', startLine: 3, endLine: 9 },
    },
    {
      id: 'entity-inventory', name: 'Inventory', kind: 'value-object', level: 'physical', change: 'same',
      desc: '库存快照 + 预占水位(值对象，带不变量)。',
      fields: [
        { name: 'SkuId', type: 'int64', visibility: 'private', desc: 'SKU', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.SkuId', kind: 'field', startLine: 3, endLine: 3 } },
        { name: 'Available', type: 'int', visibility: 'private', desc: '可售库存', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.Available', kind: 'field', startLine: 4, endLine: 4 } },
        { name: 'Reserved', type: 'int', visibility: 'private', desc: '已预占', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.Reserved', kind: 'field', startLine: 5, endLine: 5 } },
      ],
      methods: [
        { name: 'Reserve', signature: 'Reserve(qty int)', returnType: 'error', desc: '预扣，不超卖校验', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.Reserve', kind: 'method', startLine: 8, endLine: 22 } },
      ],
      ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory', kind: 'struct', startLine: 3, endLine: 6 },
    },
    {
      id: 'entity-outbox', name: 'OutboxEvent', kind: 'struct', level: 'physical', change: 'added',
      desc: '本地消息表实体(事件溯源)。',
      fields: [
        { name: 'EventId', type: 'string', visibility: 'private', desc: '事件ID(消费方去重)', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.EventId', kind: 'field', startLine: 9, endLine: 9 } },
        { name: 'Type', type: 'string', visibility: 'public', desc: '事件类型', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.Type', kind: 'field', startLine: 10, endLine: 10 } },
        { name: 'Payload', type: 'json.RawMessage', visibility: 'public', desc: '事件体', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.Payload', kind: 'field', startLine: 11, endLine: 11 } },
      ],
      methods: [
        { name: 'MarkSent', signature: 'MarkSent()', returnType: 'error', desc: '投递成功标记', ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent.MarkSent', kind: 'method', startLine: 16, endLine: 20 } },
      ],
      ast: { file: 'outbox-service/domain.go', symbol: 'OutboxEvent', kind: 'struct', startLine: 8, endLine: 14 },
    },
  ]
}

function baseFlows(): ExecutionFlow[] {
  return [
    {
      id: 'flow-place-order', name: '下单流程', trigger: 'POST /orders (带 Idempotency-Key)', change: 'modified',
      desc: '从网关接入到订单创建、库存预占、支付单创建的端到端链路；v1 引入幂等校验与事件本地落库。',
      steps: [
        { id: 's1', label: '网关鉴权/生成幂等键', owner: 'api-gateway', type: 'action', ast: { file: 'gateway/route.go', symbol: 'IdempotencyMiddleware', kind: 'method', startLine: 20, endLine: 38 } },
        { id: 's2', label: '幂等校验(唯一约束)', owner: 'order-service', type: 'decision', ast: { file: 'order-service/order.go', symbol: 'assertIdempotent', kind: 'method', startLine: 70, endLine: 85 } },
        { id: 's3', label: '库存预占', owner: 'inventory-service', type: 'io', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.Reserve', kind: 'method', startLine: 8, endLine: 22 } },
        { id: 's4', label: '创建订单(同事务写 outbox)', owner: 'order-service', type: 'action', ast: { file: 'order-service/order.go', symbol: 'CreateOrder', kind: 'func', startLine: 40, endLine: 66 } },
        { id: 's5', label: '创建支付单', owner: 'payment-service', type: 'action', ast: { file: 'payment-service/pay.go', symbol: 'CreatePayment', kind: 'func', startLine: 22, endLine: 40 } },
        { id: 's6', label: '返回待支付订单', owner: 'api-gateway', type: 'io', ast: { file: 'gateway/route.go', symbol: 'orderHandler', kind: 'method', startLine: 45, endLine: 60 } },
      ],
      sequence: {
        entities: [
          { id: 'client', name: '客户端', ast: { file: 'gateway/route.go', symbol: 'CreateOrderReq', kind: 'struct', startLine: 2, endLine: 6 } },
          { id: 'gw', name: 'api-gateway', ast: { file: 'gateway/route.go', symbol: 'orderHandler', kind: 'method', startLine: 45, endLine: 60 } },
          { id: 'order', name: 'order-service', ast: { file: 'order-service/order.go', symbol: 'CreateOrder', kind: 'func', startLine: 40, endLine: 66 } },
          { id: 'inv', name: 'inventory-service', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.Reserve', kind: 'method', startLine: 8, endLine: 22 } },
          { id: 'pay', name: 'payment-service', ast: { file: 'payment-service/pay.go', symbol: 'CreatePayment', kind: 'func', startLine: 22, endLine: 40 } },
        ],
        messages: [
          { id: 'm1', from: 'client', to: 'gw', label: 'POST /orders' },
          { id: 'm2', from: 'gw', to: 'order', label: 'CreateOrderCmd{idempotencyKey}' },
          { id: 'm3', from: 'order', to: 'inv', label: 'Reserve{skuId,qty}' },
          { id: 'm4', from: 'order', to: 'order', label: '同事务写 outbox' },
          { id: 'm5', from: 'order', to: 'pay', label: 'CreatePayment{orderNo,amount}' },
          { id: 'm6', from: 'order', to: 'gw', label: 'OrderCreated' },
        ],
      },
    },
    {
      id: 'flow-timeout-close', name: '超时关单', trigger: '定时任务(支付超时未完成)', change: 'same',
      desc: '超过支付时限未完成支付的订单自动关闭并释放库存。',
      steps: [
        { id: 't1', label: '扫描超时待支付订单', owner: 'order-service', type: 'action', ast: { file: 'order-service/close.go', symbol: 'scanExpiredOrders', kind: 'func', startLine: 4, endLine: 18 } },
        { id: 't2', label: 'CAS 关闭订单', owner: 'order-service', type: 'action', ast: { file: 'order-service/close.go', symbol: 'CloseExpiredOrder', kind: 'func', startLine: 20, endLine: 35 } },
        { id: 't3', label: '释放预占库存', owner: 'inventory-service', type: 'io', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.Release', kind: 'method', startLine: 24, endLine: 36 } },
        { id: 't4', label: '发布 OrderClosed 事件', owner: 'order-service', type: 'sync', ast: { file: 'order-service/close.go', symbol: 'emitOrderClosed', kind: 'func', startLine: 37, endLine: 45 } },
      ],
      sequence: {
        entities: [
          { id: 'sched', name: '调度器', ast: { file: 'order-service/close.go', symbol: 'closeCron', kind: 'func', startLine: 2, endLine: 3 } },
          { id: 'order', name: 'order-service', ast: { file: 'order-service/close.go', symbol: 'CloseExpiredOrder', kind: 'func', startLine: 20, endLine: 35 } },
          { id: 'inv', name: 'inventory-service', ast: { file: 'inventory-service/reserve.go', symbol: 'Inventory.Release', kind: 'method', startLine: 24, endLine: 36 } },
          { id: 'mq', name: 'rabbitmq', ast: { file: 'order-service/close.go', symbol: 'emitOrderClosed', kind: 'func', startLine: 37, endLine: 45 } },
        ],
        messages: [
          { id: 'p1', from: 'sched', to: 'order', label: '扫描超时订单' },
          { id: 'p2', from: 'order', to: 'inv', label: '释放预占库存' },
          { id: 'p3', from: 'order', to: 'mq', label: 'OrderClosed 事件' },
        ],
      },
    },
  ]
}

function baseDataFlows(): DataFlow[] {
  return [
    {
      id: 'df-order', name: '订单创建数据流', change: 'modified',
      desc: '下单请求自网关 → 订单服务 → 库存/支付；v1 增加 outbox 事件通道。',
      streams: [
        { id: 'st1', name: 'CreateOrderReq', from: 'c-gateway', to: 'c-order', payload: 'OrderRequest{idempotencyKey, items}', channel: 'HTTP', change: 'same' },
        { id: 'st2', name: 'ReserveReq', from: 'c-order', to: 'c-inventory', payload: 'ReserveRequest{skuId, qty}', channel: 'RPC(gRPC)', change: 'same' },
        { id: 'st3', name: 'OrderCreated', from: 'c-order', to: 'c-mq', payload: 'OrderCreatedEvent', channel: 'outbox → MQ', change: 'added' },
        { id: 'st4', name: 'CreatePaymentReq', from: 'c-order', to: 'c-payment', payload: 'PaymentRequest{orderNo, amount}', channel: 'RPC(gRPC)', change: 'same' },
      ],
    },
    {
      id: 'df-pay-cb', name: '支付回调数据流', change: 'same',
      desc: '支付渠道异步回调 → 验签去重 → 更新支付单 → 事件驱动订单完成。',
      streams: [
        { id: 'pc1', name: 'PayCallback', from: 'c-payment', to: 'c-payment', payload: 'Callback{corderNo, status, sign}', channel: 'HTTP', change: 'same' },
        { id: 'pc2', name: 'PaymentSucceeded', from: 'c-payment', to: 'c-mq', payload: 'PaymentSucceededEvent', channel: 'MQ', change: 'same' },
      ],
    },
  ]
}

export function buildModel(v: 'v0' | 'v1'): {
  components: ArchComponent[]; erTables: ErTable[]; ormMappings: OrmMapping[]; entityClasses: EntityClass[];
  executionFlows: ExecutionFlow[]; dataFlows: DataFlow[];
} {
  const model = {
    components: baseComponents(),
    erTables: baseErTables(),
    ormMappings: baseOrmMappings(),
    entityClasses: baseEntityClasses(),
    executionFlows: baseFlows(),
    dataFlows: baseDataFlows(),
  }
  if (v === 'v0') {
    // 基线快照: 去掉 v1 新增项，把 modified 还原为 same
    model.components = model.components.filter((c) => c.id !== 'c-outbox')
    model.components.forEach((c) => { c.change = 'same' })
    model.erTables = model.erTables.filter((t) => t.id !== 'er-outbox')
    model.erTables.forEach((t) => { t.change = 'same' })
    model.ormMappings = model.ormMappings.filter((m) => m.id !== 'orm-outbox')
    model.ormMappings.forEach((m) => { m.change = 'same' })
    model.entityClasses = model.entityClasses.filter((e) => e.id !== 'entity-outbox')
    model.entityClasses.forEach((e) => { e.change = 'same' })
    model.executionFlows.forEach((f) => { f.change = 'same'; f.steps = f.steps.filter((s) => !s.label.includes('幂等')) })
    model.dataFlows.forEach((f) => { f.change = 'same'; f.streams = f.streams.filter((s) => s.change !== 'added') })
    return model
  }
  return model
}

export const SNAPSHOT_V0: Snapshot = {
  id: 'snap-v0', name: '基线架构', version: 'v0.0.1', createdAt: Date.now() - 86400000 * 3,
  model: buildModel('v0'),
}
export const SNAPSHOT_V1: Snapshot = {
  id: 'snap-v1', name: '迭代架构(Outbox/幂等)', version: 'v1.0.0', createdAt: Date.now(),
  model: buildModel('v1'),
}

export const TASK_TREE: TaskNode = {
  id: 't-epic', title: '订单系统落地(EPIC)', kind: 'epic', status: 'in-progress', estMin: 1440,
  context: ['需求: US-1/US-2/US-3/FR-1/FR-2', '设计: 下单流程(flow-place-order)', '规约: 编码规约 v1'],
  files: ['deploy/', 'README.md'],
  children: [
    {
      id: 't-s1', title: '下单链路(STORY)', kind: 'story', status: 'in-progress', estMin: 720,
      context: ['需求: US-1/FR-1', '设计: flow-place-order / Order 结构'],
      files: ['order-service/', 'inventory-service/'],
      children: [
        { id: 't-a', title: '网关路由 + 幂等键生成', kind: 'task', status: 'in-progress', estMin: 120, context: ['NFR-1'], files: ['gateway/route.go'] },
        { id: 't-b', title: '订单服务核心下单逻辑(幂等)', kind: 'task', status: 'pending', estMin: 240, context: ['FR-1', 'Order 状态机'], files: ['order-service/order.go'] },
        { id: 't-c', title: '库存预扣与回滚', kind: 'task', status: 'pending', estMin: 180, context: ['US-3', 'Inventory 不变量'], files: ['inventory-service/reserve.go'] },
        { id: 't-d', title: '支付单创建', kind: 'task', status: 'pending', estMin: 180, context: ['US-2'], files: ['payment-service/pay.go'] },
      ],
    },
    {
      id: 't-s2', title: '可靠事件(OUTBOX)', kind: 'story', status: 'pending', estMin: 480,
      context: ['需求: FR-2/NFR-1', '设计: OutboxEvent 结构 / 订单创建数据流'],
      files: ['outbox-service/', 'mq/'],
      children: [
        { id: 't-e', title: 'outbox 中继组件', kind: 'task', status: 'pending', estMin: 240, context: ['FR-2', '同事务写 outbox'], files: ['outbox-service/relay.go'] },
        { id: 't-f', title: '超时关单定时任务', kind: 'task', status: 'pending', estMin: 120, context: ['US-2', 'flow-timeout-close'], files: ['order-service/close.go'] },
      ],
    },
    {
      id: 't-s3', title: '质量保障(STORY)', kind: 'story', status: 'pending', estMin: 240,
      context: ['需求: NFR-2', '验收: 架构质量验收'],
      files: ['tests/'],
      children: [
        { id: 't-g', title: '集成测试(下单→支付→关单)', kind: 'task', status: 'pending', estMin: 180, context: ['验收标准'], files: ['tests/integration_test.go'] },
        { id: 't-h', title: '架构质量验收检查', kind: 'check', status: 'pending', estMin: 60, context: ['质量检查清单'], files: ['quality-report.md'] },
      ],
    },
  ],
}

export const CODING_RULES = `# 编码规约 v1.0

## 通用约定
- 语言: 核心链路 Go(服务) / Java(支付领域)，存储层遵循团队模板
- 风格: 统一 gofmt + golangci-lint / checkstyle，禁止尾随空白
- 提交: Conventional Commits(如 \`feat(order): 幂等校验\`)，每次提交必须可独立构建

## 领域规则
- 状态机变更必须走统一 \`transition()\`，禁止旁路修改状态字段
- 幂等键一律取自请求头 \`Idempotency-Key\`，落到 \`idempotency_key\` 唯一约束
- 事件写入与业务变更必须**同一数据库事务**(本地 outbox)

## 数据访问
- 写操作使用乐观锁(\`version\` CAS)，重试上限 3 次
- 禁止在业务事务内调用外部 RPC/HTTP(会破坏一致性)，一律改事件
- 查询路径默认走缓存，缓存击穿需加互斥重建

## 测试
- 单测覆盖率目标 ≥ 80%(核心领域)
- 集成测试必须覆盖: 下单幂等 / 库存回滚 / 支付回调去重
`

export const QUALITY_CHECKS: { id: string; name: string; desc: string; level: 'blocker' | 'major' | 'minor'; pass: boolean }[] = [
  { id: 'q1', name: '组件边界检查', desc: '跨组件调用仅允许经由公开接口，禁止服务间直连数据库', level: 'blocker', pass: true },
  { id: 'q2', name: '依赖方向检查', desc: '领域层不得依赖基础设施层(依赖倒置)', level: 'blocker', pass: true },
  { id: 'q3', name: '状态机完整度', desc: '所有状态变迁均通过 transition() 且记录审计', level: 'major', pass: true },
  { id: 'q4', name: '幂等唯一约束', desc: 'idempotency_key 具备唯一索引并在代码路径覆盖', level: 'blocker', pass: true },
  { id: 'q5', name: '事务边界检查', desc: '业务事务内不存在外部 I/O(已迁移为事件)', level: 'major', pass: true },
  { id: 'q6', name: '循环依赖检测', desc: '组件依赖图无环', level: 'blocker', pass: false },
  { id: 'q7', name: '测试覆盖率门槛', desc: '核心领域单测覆盖率 ≥ 80%', level: 'minor', pass: false },
  { id: 'q8', name: 'API 兼容性', desc: '迭代改造未破坏对外 API 契约(幂等键为新增可选头)', level: 'major', pass: true },
]

export const INITIAL_SESSIONS: Record<string, AgentSession> = {
  'ex-1': {
    id: 'sess-ex-1', taskId: 'ex-1', adapter: 'opencode', status: 'working', keepContext: true,
    messages: [
      {
        id: 'm1', role: 'user', time: Date.now() - 1000000,
        content: '执行方案 plan-1(下单主链路 + 幂等加固)。上下文: [US-1/FR-1, flow-place-order, 规约 v1]',
      },
      {
        id: 'm2', role: 'assistant', time: Date.now() - 980000,
        content: '计划: 1) 网关新增 Idempotency-Key 过滤器  2) 订单核心同事务写 outbox  3) 幂等唯一约束落库。',
      },
      {
        id: 'm3', role: 'tool', time: Date.now() - 960000,
        tool: { type: 'write-file', label: 'gateway/middleware/idempotency.go', detail: '创建过滤器 + 键生成器(sha256) 156 行', ok: true },
        content: '',
      },
      {
        id: 'm4', role: 'tool', time: Date.now() - 940000,
        tool: { type: 'run-command', label: 'go test ./middleware/...', detail: '新增用例 8 个，全部通过', ok: true },
        content: '',
      },
      {
        id: 'm5', role: 'assistant', time: Date.now() - 920000,
        content: '已完成幂等键中间件，8 个单测通过。下一步联调订单服务幂等校验。',
      },
    ],
    artifacts: ['gateway/middleware/idempotency.go'],
    testResult: { passed: 8, failed: 0, note: 'go test ./middleware/... 通过' },
  },
  'ex-2': {
    id: 'sess-ex-2', taskId: 'ex-2', adapter: 'codex', status: 'idle', keepContext: true,
    messages: [
      {
        id: 'm1', role: 'user', time: Date.now() - 500000,
        content: '执行方案 plan-2(可靠事件 + 可用性保障)。上下文: [FR-2/NFR-1, 编码规约 v1]',
      },
      {
        id: 'm2', role: 'assistant', time: Date.now() - 480000,
        content: '计划: 1) outbox 中继组件  2) 回调验签去重  3) 缓存降级。等待你确认后开始。',
      },
    ],
    artifacts: [],
  },
}

export const MIGRATION_MD = `# 架构变更迁移对比报告

> 基线 **v0.0.1**(monolith 事件经同步 RPC 通知) → 目标 **v1.0.0**(outbox 可靠事件 + 幂等加固)

## 变更摘要
| 变更 | 影响组件 | 迁移方式 |
| --- | --- | --- |
| 新增 outbox-service | order-service → MQ | 新增组件，事件入库与业务同事务 |
| 订单引入幂等键 | order-service / gateway | 唯一约束 + 状态机扩展 |
| 支付渠道适配层 | payment-service | 适配层 DTO，渠道切换零侵入 |
| 事务边界清理 | 全部 | 业务事务内外部 I/O 迁移为事件 |

## 组件树差异
- \`added\`  outbox-service(gateway 无感)
- \`modified\` order-service(幂等/事件落库) · payment-service(适配层)
- \`same\`  gateway / inventory-service / mysql-cluster / rabbitmq

## 数据结构差异
- \`added\` OutboxEvent · PaymentGatewayRef
- \`modified\` Order(+\`idempotency_key\`/version 乐观锁)
- \`same\`  OrderItem / Payment / Inventory

## 数据流差异
- \`added\`  OrderCreated 事件通道(order → outbox → MQ)
- \`same\`  支付回调链路

## 风险与对策
- 事件投递顺序: 单 key 有序 + 消费方按 event_id 去重
- 灰度: 网关幂等键先灰度 5% 流量，验证重复率观测
- 回滚: v1 新增列均 nullable，旧版本代码可无损共存
`

export const ARCHITECTURE_SPEC: ArchitectureSpec = {
  version: 'spec-v1.2',
  overrides: [
    { file: 'order-service/order.go', communityKey: 'comm-order', pinned: true, note: '人工钉点: 订单领域核心，禁止算法移动' },
    { file: 'payment-service/pay.go', communityKey: 'comm-payment', pinned: true, note: '人工钉点: 支付领域边界' },
    { file: 'gateway/middleware/idempotency.go', communityKey: 'comm-gateway', pinned: false, note: '手动指派到网关社区' },
  ],
  explicitRules: [
    { id: 'R-1', text: '组件 order-service 不得依赖 payment-service 的内部实现', level: 'blocker', source: 'explicit' },
    { id: 'R-2', text: '核心文件 (order.go / pay.go) 禁止删改，仅允许扩展新增方法', level: 'blocker', source: 'explicit' },
    { id: 'R-3', text: '新增跨组件调用必须经公开接口 (RPC/事件)，禁止直连数据库', level: 'major', source: 'explicit' },
  ],
  derivedRules: [
    { id: 'D-1', text: '依赖方向: 领域层不得依赖基础设施层 (依赖倒置)', level: 'blocker', source: 'derived' },
    { id: 'D-2', text: '关键节点保护: mysql-cluster 仅允许数据层访问', level: 'major', source: 'derived' },
    { id: 'D-3', text: '社区职责: comm-order 不得与 comm-payment 合并', level: 'major', source: 'derived' },
  ],
  changelog: [
    { version: 'spec-v1.2', date: Date.now() - 3600000, note: '新增 R-3 跨组件调用经公开接口', confirmedBy: '架构师·人工确认' },
    { version: 'spec-v1.1', date: Date.now() - 86400000, note: '钉点 order.go / pay.go', confirmedBy: '架构师·人工确认' },
  ],
}

export const STAGING_MODEL: StagingModel = {
  scope: {
    filesChanged: ['order-service/order.go', 'order-service/service.go', 'order-service/close.go', 'outbox-service/relay.go', 'tests/integration_test.go'],
    added: 2,
    modified: 3,
    deleted: 0,
    deletedHighRisk: false,
  },
  grade: 'M',
  gradeBasis: '修改 3 文件 + 新增 2 文件 · 触及枢纽 order-service · 无删除',
  gradeAction: '社区层精化(refinement) + 语义层脏标记懒重解释',
  affectedComponents: ['order-service', 'outbox-service', 'inventory-service'],
  layers: {
    file: { reParsed: 5, reusedByHash: 12, edgesChanged: 7 },
    community: { refined: 2, dirty: 3, action: '以旧 partition 为种子跑 Leiden refinement' },
    semantic: { reExplained: 1, dirty: 3, inherited: 9 },
  },
}

export const INCREMENTAL_LOG: IncrementalLogEntry[] = [
  {
    id: 'inc-1', time: Date.now() - 600000, scope: 'execution batch #2 (outbox)', grade: 'M',
    files: ['outbox-service/relay.go', 'outbox-service/domain.go'],
    edgesChanged: 3, reExplained: ['comm-order', 'comm-mq'], boundaryChanged: [],
  },
  {
    id: 'inc-2', time: Date.now() - 300000, scope: 'execution batch #3 (订单核心)', grade: 'S',
    files: ['order-service/order.go', 'order-service/service.go'],
    edgesChanged: 4, reExplained: ['comm-order'], boundaryChanged: [],
  },
]

export const COMPLIANCE_CHECKS: ComplianceCheck[] = [
  { id: 'c-b1', name: '边界越界检查', kind: 'boundary', pass: true, level: 'blocker', detail: '无文件跨越人工钉点边界', scope: 'order-service/' },
  { id: 'c-s1', name: '规约违反检查', kind: 'spec', pass: true, level: 'blocker', detail: '未新增 order → payment 内部依赖', scope: 'order-service/service.go' },
  { id: 'c-k1', name: '关键节点保护', kind: 'critical', pass: true, level: 'blocker', detail: '核心文件未删除/改名', scope: 'order.go · pay.go' },
  { id: 'c-d1', name: '依赖方向检查', kind: 'direction', pass: false, level: 'major', detail: 'outbox-service 出现对 mysql-cluster 的直接 DDL 依赖，需改经数据层', scope: 'outbox-service/relay.go' },
]

export const EXTERNAL_CALLS: ExternalCall[] = [
  {
    id: 'x-1', source: 'cursor', tool: 'architect.context.get', method: 'read',
    time: Date.now() - 90000, status: 'ok', detail: '获取订单核心上下文包(6 文件 · 依赖边 7)',
  },
  {
    id: 'x-2', source: 'claude-code', tool: 'architect.spec.get', method: 'read',
    time: Date.now() - 60000, status: 'ok', detail: '读取架构规约 R-1..R-3 · D-1..D-3',
  },
  {
    id: 'x-3', source: 'github-copilot', tool: 'architect.overrides.set', method: 'write',
    time: Date.now() - 30000, status: 'blocked', detail: '尝试移动钉点 pay.go → 拒绝(硬约束)',
  },
  {
    id: 'x-4', source: 'cursor', tool: 'architect.compliance.run', method: 'invoke',
    time: Date.now() - 10000, status: 'pending', detail: '对 outbox-service 提交触发合规校验',
  },
]

export const CODE_MAPPINGS: CodeMapping[] = [
  { id: 'cm-1', targetType: 'component', targetId: 'c-gateway', targetName: 'api-gateway', file: 'gateway/route.go', line: 'L1-38', level: 'physical', note: '路由注册与鉴权中间件' },
  { id: 'cm-2', targetType: 'component', targetId: 'c-order', targetName: 'order-service', file: 'order-service/order.go', line: 'L12-89', level: 'physical', note: '订单状态机与领域逻辑' },
  { id: 'cm-3', targetType: 'component', targetId: 'c-order', targetName: 'order-service', file: 'order-service/service.go', line: 'L5-67', level: 'physical', note: '下单用例编排' },
  { id: 'cm-4', targetType: 'entity', targetId: 'entity-order', targetName: 'Order', file: 'order-service/order.go', line: 'L3-11', level: 'physical', note: 'Order 实体定义' },
  { id: 'cm-5', targetType: 'er', targetId: 'er-order', targetName: 'orders 表', file: 'order-service/order.go', line: 'L3-11', level: 'physical', note: '订单主表映射' },
  { id: 'cm-6', targetType: 'entity', targetId: 'entity-outbox', targetName: 'OutboxEvent', file: 'outbox-service/domain.go', line: 'L8-20', level: 'physical', note: '本地消息表实体' },
  { id: 'cm-7', targetType: 'flow', targetId: 'flow-place-order', targetName: '下单流程', file: 'order-service/service.go', line: 'L5-67', level: 'logical', note: '下单端到端编排' },
  { id: 'cm-8', targetType: 'flow', targetId: 'flow-timeout-close', targetName: '超时关单', file: 'order-service/close.go', line: 'L1-45', level: 'logical', note: '定时关单 + 库存释放' },
  { id: 'cm-9', targetType: 'dataflow', targetId: 'df-order', targetName: '订单创建数据流', file: 'order-service/service.go', line: 'L40-60', level: 'logical', note: '事件写 outbox → MQ 投递' },
]

export const USER_INTERACTIONS: UserInteraction[] = [
  {
    id: 'ui-1', kind: 'issue', taskId: 'ex-1', status: 'pending', createdAt: Date.now() - 600000,
    prompt: '订单服务单测覆盖率为 72%，低于规约要求的 80%。是否允许本次任务以 72% 交付并列入后续整改？',
    options: ['允许交付并记录整改项', '强制补齐至 80% 后再完成'],
  },
  {
    id: 'ui-2', kind: 'choice', taskId: 'ex-1', status: 'pending', createdAt: Date.now() - 300000,
    prompt: '库存预扣遇到并发写冲突，采用哪种重试策略？',
    options: ['乐观锁 CAS 重试(上限 3 次)', '分布式锁(引入中间件)', '串行化(性能损失)'],
  },
  {
    id: 'ui-3', kind: 'info', taskId: 'ex-3', status: 'resolved', createdAt: Date.now() - 86400000,
    prompt: '超时关单定时任务的执行窗口需要补充确认。',
    options: ['每 5 分钟', '每 1 分钟'],
    answer: '每 1 分钟',
  },
]
