/**
 * Pattern Gallery —— 内置设计模式/示例库，供引导工作流与 DesignTree 示例使用。
 *
 * 示例内容只展示「结构/格式」，不绑定用户真实数据。
 * 按产品形态（ui-ue / io）和任务类型（form/stack/requirement/blueprint/scaffold）索引。
 */

export interface GalleryEntry {
  title: string
  content: string
  /** Markdown / mermaid / 代码块 */
  kind: 'md' | 'mermaid' | 'code'
}

const PATTERNS: Record<string, GalleryEntry[]> = {
  'io.product-form': [
    { title: '服务划分参考', content: '## 订单系统服务建议\n\n- **网关层**：请求路由、认证、限流\n- **订单服务**：订单 CRUD、状态机\n- **支付服务**：渠道适配、回调处理\n- **库存服务**：预扣、释放、快照\n- **消息中继**：outbox、死信、重试', kind: 'md' },
  ],
  'ui-ue.product-form': [
    { title: '页面树参考', content: '```mermaid\ngraph TD\n  A[用户端] --> B[商品浏览]\n  A --> C[下单]\n  A --> D[订单列表]\n  A --> E[个人中心]\n  C --> C1[选择地址]\n  C --> C2[确认支付]\n  C --> C3[支付成功]\n```', kind: 'mermaid' },
  ],
  'io.stack': [
    { title: 'Go + Gin 项目结构', content: '```\nmy-service/\n├── cmd/server/main.go\n├── internal/\n│   ├── config/config.go\n│   ├── handler/   # HTTP 处理器\n│   ├── domain/    # 领域逻辑\n│   ├── repo/      # 数据访问\n│   └── middleware/\n├── pkg/           # 共享库\n├── go.mod\n├── Dockerfile\n└── Makefile\n```', kind: 'code' },
  ],
  'ui-ue.stack': [
    { title: 'Vue 3 前端结构', content: '```\nmy-app/\n├── src/\n│   ├── views/      # 页面\n│   ├── components/ # 可复用组件\n│   ├── stores/     # 状态管理\n│   ├── router/     # 路由\n│   ├── api/        # API 请求\n│   └── App.vue\n├── package.json\n├── vite.config.ts\n├── Dockerfile\n└── README.md\n```', kind: 'code' },
  ],
  'io.requirement': [
    { title: '需求样例（I/O 型）', content: '## 用户 Story：可靠事件投递\n\n**描述**：订单领域事件需可靠投递至消息中间件，不丢不重。\n\n**可验收标准**：\n- 业务变更与事件写入在同一事务\n- 投递失败进入死信，支持手动重试\n- 消费端幂等去重\n\n**功能范围**：order-service、outbox-service\n**业务实体**：Order、OutboxEvent、DeliveryLog', kind: 'md' },
  ],
  'ui-ue.requirement': [
    { title: '需求样例（UI 型）', content: '## 用户 Story：下单页面\n\n**描述**：用户可浏览商品、添加到购物车、填写地址后提交订单。\n\n**可验收标准**：\n- 商品列表可搜索/筛选\n- 购物车可增删改\n- 下单后展示确认页\n\n**涉及页面**：商品列表 → 商品详情 → 购物车 → 下单 → 支付确认', kind: 'md' },
  ],
  'io.blueprint': [
    { title: 'ER 图示例', content: '```mermaid\nerDiagram\n  ORDER ||--o{ ORDER_ITEM : has\n  ORDER ||--|| OUTBOX_EVENT : produces\n  ORDER }|--|| USER : belongs-to\n  ORDER_ITEM }|--|| PRODUCT : references\n  ORDER {\n    string id PK\n    string status\n    datetime created_at\n    string user_id FK\n  }\n```', kind: 'mermaid' },
  ],
  'ui-ue.blueprint': [
    { title: '交互流示例', content: '```mermaid\nsequenceDiagram\n  User->>+Browser: 点击「立即购买」\n  Browser->>+Gateway: POST /api/orders\n  Gateway->>+OrderSvc: CreateOrder\n  OrderSvc->>-Gateway: OrderID + Status\n  Gateway->>-Browser: 201 Created\n  Browser->>-User: 跳转支付页\n```', kind: 'mermaid' },
  ],
  'io.scaffold': [
    { title: 'Go 骨架文件树', content: '```\norder-service/\n├── cmd/server/main.go     (server bootstrap)\n├── internal/\n│   ├── config/config.go   (viper 配置)\n│   ├── domain/            (空 domain 包)\n│   ├── repo/              (空 repo 包)\n│   └── middleware/        (幂等/日志中间件壳)\n├── go.mod\n├── Dockerfile\n└── Makefile\n```', kind: 'code' },
  ],
  'ui-ue.scaffold': [
    { title: 'Vue 骨架文件树', content: '```\norder-app/\n├── src/\n│   ├── views/Home.vue     (首页壳)\n│   ├── views/Order.vue    (订单页壳)\n│   ├── components/        (空组件库)\n│   ├── stores/            (空 store)\n│   ├── router/index.ts    (路由表)\n│   ├── api/index.ts       (API 调用壳)\n│   └── App.vue\n├── package.json\n├── vite.config.ts\n└── Dockerfile\n```', kind: 'code' },
  ],
}

export function getPattern(key: string): GalleryEntry | undefined {
  const entries = PATTERNS[key]
  return entries?.[0]
}

export function getPatterns(key: string): GalleryEntry[] {
  return PATTERNS[key] ?? []
}

export function allPatternKeys(): string[] {
  return Object.keys(PATTERNS)
}