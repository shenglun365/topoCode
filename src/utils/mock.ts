/** Mock 数据 - 模拟后端服务 */
import type { Project, AnalysisTask, KnowledgeDoc } from '@/types'

/** 语言 badge 颜色映射 */
export const languageBadge: Record<string, string> = {
  Python: 'badge-green',
  Go: 'badge-cyan',
  JavaScript: 'badge-blue',
  TypeScript: 'badge-blue',
  Java: 'badge-red',
  Rust: 'badge-orange',
  HTML: 'badge-orange',
  C: 'badge-blue',
  'C++': 'badge-purple',
  Vue: 'badge-emerald',
}

/** Mock 项目列表 */
export const mockProjects: Project[] = [
  {
    id: 'proj-1',
    name: 'topoOne-ui',
    path: '/home/cuser/topoCodeProj/topoOne-ui',
    language: 'JavaScript',
    fileCount: 128,
    status: 'synced',
    lastSync: '2026-05-01T09:30:00',
    createdAt: '2026-04-01T00:00:00',
  },
  {
    id: 'proj-2',
    name: 'backend-api',
    path: '/home/cuser/projects/backend-api',
    language: 'Go',
    fileCount: 256,
    status: 'syncing',
    lastSync: '2026-04-25T14:00:00',
    createdAt: '2026-03-15T00:00:00',
  },
  {
    id: 'proj-3',
    name: 'data-pipeline',
    path: '/home/cuser/projects/data-pipeline',
    language: 'Rust',
    fileCount: 64,
    status: 'synced',
    lastSync: '2026-04-10T08:00:00',
    createdAt: '2026-02-01T00:00:00',
  },
]

/** Mock 分析任务列表 */
export const mockTasks: AnalysisTask[] = [
  {
    id: 'task-1',
    projectId: 'proj-1',
    type: 'full-parse',
    name: '全量解析',
    status: 'done',
    total: 128,
    current: 128,
    progress: 100,
    createdAt: '2026-05-01T09:00:00',
    updatedAt: '2026-05-01T09:30:00',
    favorite: false,
    pinned: false,
    tags: ['认证'],
  },
  {
    id: 'task-2',
    projectId: 'proj-1',
    type: 'ast-gen',
    name: 'AST 生成',
    status: 'running',
    total: 128,
    current: 83,
    progress: 65,
    createdAt: '2026-05-01T10:00:00',
    updatedAt: '2026-05-01T10:15:00',
    favorite: false,
    pinned: true,
    tags: ['核心'],
  },
  {
    id: 'task-3',
    projectId: 'proj-1',
    type: 'call-chain',
    name: '调用链分析',
    status: 'pending',
    createdAt: '2026-05-01T10:30:00',
    updatedAt: '2026-05-01T10:30:00',
    favorite: true,
    pinned: false,
    tags: ['认证', 'API'],
  },
  {
    id: 'task-4',
    projectId: 'proj-1',
    type: 'dataflow',
    name: '数据流分析',
    status: 'error',
    error: '解析器配置错误',
    createdAt: '2026-05-01T11:00:00',
    updatedAt: '2026-05-01T11:05:00',
    favorite: true,
    pinned: true,
    tags: ['错误处理'],
  },
  {
    id: 'task-5',
    projectId: 'proj-2',
    type: 'dep-analysis',
    name: '依赖分析',
    status: 'done',
    total: 256,
    current: 256,
    progress: 100,
    createdAt: '2026-04-28T09:00:00',
    updatedAt: '2026-04-28T09:45:00',
    favorite: false,
    pinned: false,
    tags: ['API'],
  },
]

/** Mock 文件树节点 */
export interface MockFileNode {
  name: string
  path: string
  type: 'file' | 'directory'
  language?: string
  children?: MockFileNode[]
}

/** Mock 文件树 */
export const mockFileTree: MockFileNode[] = [
  {
    name: 'topoOne-ui',
    path: '/',
    type: 'directory',
    children: [
      {
        name: '.qwen',
        path: '/.qwen',
        type: 'directory',
        children: [
          { name: 'settings.json', path: '/.qwen/settings.json', type: 'file', language: 'JSON' },
        ],
      },
      {
        name: 'docs',
        path: '/docs',
        type: 'directory',
        children: [
          { name: '需求文档.md', path: '/docs/需求文档.md', type: 'file', language: 'Markdown' },
          { name: 'GUI交互层设计方案.md', path: '/docs/GUI交互层设计方案.md', type: 'file', language: 'Markdown' },
          { name: 'ui功能点.txt', path: '/docs/ui功能点.txt', type: 'file' },
          { name: '系统架构设计.md', path: '/docs/系统架构设计.md', type: 'file', language: 'Markdown' },
        ],
      },
      {
        name: 'prototype',
        path: '/prototype',
        type: 'directory',
        children: [
          {
            name: 'css',
            path: '/prototype/css',
            type: 'directory',
            children: [
              { name: 'style.css', path: '/prototype/css/style.css', type: 'file', language: 'CSS' },
              { name: 'layout.css', path: '/prototype/css/layout.css', type: 'file', language: 'CSS' },
              { name: 'components.css', path: '/prototype/css/components.css', type: 'file', language: 'CSS' },
            ],
          },
          {
            name: 'js',
            path: '/prototype/js',
            type: 'directory',
            children: [
              { name: 'app.js', path: '/prototype/js/app.js', type: 'file', language: 'JavaScript' },
            ],
          },
          {
            name: 'pages',
            path: '/prototype/pages',
            type: 'directory',
            children: [
              { name: 'home.html', path: '/prototype/pages/home.html', type: 'file', language: 'HTML' },
              { name: 'analysis.html', path: '/prototype/pages/analysis.html', type: 'file', language: 'HTML' },
              { name: 'knowledge.html', path: '/prototype/pages/knowledge.html', type: 'file', language: 'HTML' },
              { name: 'coder.html', path: '/prototype/pages/coder.html', type: 'file', language: 'HTML' },
              { name: 'user.html', path: '/prototype/pages/user.html', type: 'file', language: 'HTML' },
            ],
          },
          { name: 'index.html', path: '/prototype/index.html', type: 'file', language: 'HTML' },
        ],
      },
      {
        name: 'src',
        path: '/src',
        type: 'directory',
        children: [
          { name: 'main.ts', path: '/src/main.ts', type: 'file', language: 'TypeScript' },
          { name: 'App.vue', path: '/src/App.vue', type: 'file', language: 'Vue' },
          {
            name: 'components',
            path: '/src/components',
            type: 'directory',
            children: [],
          },
          {
            name: 'stores',
            path: '/src/stores',
            type: 'directory',
            children: [],
          },
        ],
      },
      { name: 'package.json', path: '/package.json', type: 'file', language: 'JSON' },
      { name: 'vite.config.ts', path: '/vite.config.ts', type: 'file', language: 'TypeScript' },
      { name: 'tsconfig.json', path: '/tsconfig.json', type: 'file', language: 'JSON' },
      { name: 'index.html', path: '/index.html', type: 'file', language: 'HTML' },
    ],
  },
]

/** 任务类型名称映射 */
export const taskTypeNames: Record<string, string> = {
  'full-parse': '全量解析',
  'ast-gen': 'AST 生成',
  'call-chain': '调用链分析',
  'dataflow': '数据流分析',
  'dep-analysis': '依赖分析',
}

/** 任务状态名称映射 */
export const taskStatusNames: Record<string, string> = {
  done: '完成',
  running: '进行中',
  pending: '待开始',
  error: '失败',
}

/** 任务状态 badge 颜色 */
export const taskStatusBadge: Record<string, string> = {
  done: 'badge-green',
  running: 'badge-yellow',
  pending: 'badge-gray',
  error: 'badge-red',
}

/** 格式化时间 */
export function formatTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))

  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 7) return `${days}天前`
  if (days < 30) return `${Math.floor(days / 7)}周前`
  return `${Math.floor(days / 30)}个月前`
}

/** 模拟延迟 */
export function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

// ==================== 知识库 Mock 数据 ====================

/** 四维分类标签 */
export const knowledgeDimensions = {
  lifecycle: ['需求', '设计', '编码', '测试', '部署', '运维', '重构'],
  techStack: ['Python', 'Go', 'JavaScript', '数据库', 'Docker', 'CI-CD'],
  abstraction: ['架构', '模块', '类', '函数', '配置', '数据'],
  purpose: ['最佳实践', '设计模式', '常见陷阱', '规范', '分析结果', '教学素材'],
}

/** 维度颜色 */
export const dimensionColors: Record<string, string> = {
  lifecycle: 'badge-blue',
  techStack: 'badge-green',
  abstraction: 'badge-yellow',
  purpose: 'badge-red',
}

/** Mock 知识点文档 */
export const mockKnowledgeDocs: KnowledgeDoc[] = [
  {
    id: 'doc-1',
    title: 'JWT 认证规范',
    type: 'document',
    description: 'JWT token 的生成、验证、刷新完整流程，包含签名算法选择、过期时间设置',
    content: '# JWT 认证规范\n\n## 概述\n本文档描述了 TopoOne 系统中 JWT 认证的完整流程。\n\n## 技术栈\n- **语言**: Python\n- **框架**: FastAPI\n- **库**: PyJWT, passlib',
    projectId: 'proj-1',
    tags: { lifecycle: ['设计'], techStack: ['Python'], abstraction: ['模块'], purpose: ['最佳实践'] },
    status: 'reviewed',
    favorite: true,
    pinned: false,
    createdAt: '2026-04-20T00:00:00',
    updatedAt: '2026-05-02T00:00:00',
  },
  {
    id: 'doc-2',
    title: '微服务架构设计',
    type: 'document',
    description: '核心模块依赖 auth、api、models 三个子模块，通过 HTTP/gRPC 与外部服务通信',
    content: '# 微服务架构设计\n\n## 概述\n系统采用微服务架构，核心模块包括认证、API网关、数据模型。\n\n## 模块划分\n- auth: 认证授权服务\n- api: API 网关\n- models: 数据模型层',
    projectId: 'proj-2',
    tags: { lifecycle: ['设计'], techStack: ['Go'], abstraction: ['架构'], purpose: ['分析结果'] },
    status: 'reviewed',
    favorite: false,
    pinned: true,
    createdAt: '2026-03-10T00:00:00',
    updatedAt: '2026-04-25T00:00:00',
  },
  {
    id: 'doc-3',
    title: '数据库连接池配置',
    type: 'document',
    description: '连接池最小连接数设为预期并发量的 50%，最大连接数 200，超时 30s',
    content: '# 数据库连接池配置\n\n## 参数说明\n- 最小连接数: 预期并发量的 50%\n- 最大连接数: 200\n- 超时时间: 30s',
    projectId: 'proj-2',
    tags: { lifecycle: ['运维'], techStack: ['数据库'], abstraction: ['配置'], purpose: ['最佳实践'] },
    status: 'pending',
    favorite: false,
    pinned: false,
    createdAt: '2026-04-05T00:00:00',
    updatedAt: '2026-04-30T00:00:00',
  },
  {
    id: 'doc-4',
    title: 'RESTful API 设计规范',
    type: 'document',
    description: '资源命名使用复数名词，HTTP 方法对应 CRUD 操作，版本控制通过 URL 路径实现',
    content: '# RESTful API 设计规范\n\n## 命名规范\n- 资源命名使用复数名词\n- HTTP 方法对应 CRUD 操作\n- 版本控制通过 URL 路径实现',
    projectId: 'proj-2',
    tags: { lifecycle: ['设计'], techStack: ['Go'], abstraction: ['模块'], purpose: ['规范'] },
    status: 'draft',
    favorite: false,
    pinned: false,
    createdAt: '2026-02-20T00:00:00',
    updatedAt: '2026-04-15T00:00:00',
  },
  {
    id: 'doc-5',
    title: 'SQL 注入防御指南',
    type: 'document',
    description: '使用参数化查询替代字符串拼接，所有用户输入经过白名单校验',
    content: '# SQL 注入防御指南\n\n## 防御措施\n1. 使用参数化查询\n2. 用户输入白名单校验\n3. ORM 框架优先',
    projectId: 'proj-2',
    tags: { lifecycle: ['编码'], techStack: ['数据库'], abstraction: ['函数'], purpose: ['常见陷阱'] },
    status: 'reviewed',
    favorite: true,
    pinned: false,
    createdAt: '2026-04-10T00:00:00',
    updatedAt: '2026-04-28T00:00:00',
  },
  {
    id: 'doc-6',
    title: 'Docker 部署手册',
    type: 'document',
    description: 'Dockerfile 编写规范、多阶段构建、docker-compose 编排配置',
    content: '# Docker 部署手册\n\n## Dockerfile 规范\n- 多阶段构建\n- 最小基础镜像\n- 非 root 用户运行',
    projectId: 'proj-3',
    tags: { lifecycle: ['部署'], techStack: ['Docker'], abstraction: ['配置'], purpose: ['规范'] },
    status: 'reviewed',
    favorite: false,
    pinned: false,
    createdAt: '2026-04-15T00:00:00',
    updatedAt: '2026-04-26T00:00:00',
  },
  {
    id: 'doc-7',
    title: '数据流转动画脚本',
    type: 'document',
    description: 'Request → 提取 → 验证 → User/Error 的完整数据流路径，D3.js 力导向图',
    content: '# 数据流转动画脚本\n\n## 动画流程\nRequest → 提取 → 验证 → User/Error\n\n## 技术实现\n使用 D3.js 力导向图实现数据流可视化',
    projectId: 'proj-1',
    tags: { lifecycle: ['设计'], techStack: ['JavaScript'], abstraction: ['数据'], purpose: ['教学素材'] },
    status: 'reviewed',
    favorite: false,
    pinned: false,
    createdAt: '2026-04-18T00:00:00',
    updatedAt: '2026-04-29T00:00:00',
  },
]

/** Mock 知识图谱节点 */
export interface KnowledgeGraphNode {
  id: string
  label: string
  type: 'module' | 'class' | 'function' | 'knowledge'
  x: number
  y: number
  color: string
}

/** Mock 知识图谱边 */
export interface KnowledgeGraphEdge {
  from: string
  to: string
  type: 'dependency' | 'reference'
}

export const mockGraphNodes: KnowledgeGraphNode[] = [
  { id: 'core', label: 'core', type: 'module', x: 350, y: 200, color: 'var(--accent)' },
  { id: 'auth', label: 'auth', type: 'class', x: 200, y: 100, color: 'var(--success)' },
  { id: 'api', label: 'api', type: 'class', x: 500, y: 100, color: 'var(--warning)' },
  { id: 'models', label: 'models', type: 'class', x: 200, y: 320, color: 'var(--error)' },
  { id: 'utils', label: 'utils', type: 'class', x: 500, y: 320, color: 'var(--text-muted)' },
  { id: 'jwt', label: 'JWT认证', type: 'knowledge', x: 100, y: 140, color: 'var(--accent)' },
  { id: 'rest', label: 'REST规范', type: 'knowledge', x: 620, y: 140, color: 'var(--accent)' },
  { id: 'pool', label: '连接池', type: 'knowledge', x: 100, y: 360, color: 'var(--accent)' },
]

export const mockGraphEdges: KnowledgeGraphEdge[] = [
  { from: 'core', to: 'auth', type: 'dependency' },
  { from: 'core', to: 'api', type: 'dependency' },
  { from: 'core', to: 'models', type: 'dependency' },
  { from: 'core', to: 'utils', type: 'dependency' },
  { from: 'jwt', to: 'auth', type: 'reference' },
  { from: 'rest', to: 'api', type: 'reference' },
  { from: 'pool', to: 'models', type: 'reference' },
]

// ==================== AI 助手 Mock 数据 ====================

/** AI 会话 */
export interface ChatSession {
  id: string
  title: string
  mode: 'chat' | 'design'
  status: 'idle' | 'running' | 'done'
  messages: ChatMessage[]
  createdAt: string
  updatedAt: string
}

/** 聊天消息 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  // AI 回复扩展字段
  contextCards?: ContextCard[]
  specSummary?: SpecSummary
  taskStatus?: TaskStatus
  actions?: string[]
}

/** 上下文检索卡片 */
export interface ContextCard {
  id: string
  type: 'knowledge' | 'code' | 'analysis'
  title: string
  description: string
  tags: string[]
}

/** Spec 摘要 */
export interface SpecSummary {
  fileName: string
  status: 'draft' | 'approved' | 'executing'
  targetFile: string
  dependencies: string[]
  constraints: string[]
  functionSignatures: string[]
  createdAt: string
}

/** 任务状态 */
export interface TaskStatus {
  id: string
  name: string
  status: 'pending' | 'running' | 'done' | 'error'
  agent: string
  elapsed: string
  filesGenerated: number
  terminalLines: TerminalLine[]
  validations: ValidationItem[]
}

/** 终端行 */
export interface TerminalLine {
  text: string
  type: 'info' | 'success' | 'error'
}

/** 校验项 */
export interface ValidationItem {
  label: string
  passed: boolean
}

/** Mock 会话列表 */
export const mockSessions: ChatSession[] = [
  {
    id: 'session-1',
    title: 'Redis 会话管理器',
    mode: 'design',
    status: 'done',
    createdAt: '2026-05-03T14:30:00',
    updatedAt: '2026-05-03T14:37:00',
    messages: [
      {
        id: 'msg-1',
        role: 'user',
        content: '帮我实现一个基于 Redis 的用户会话管理模块，需符合知识库中的安全规范。',
        timestamp: '2026-05-03T14:32:00',
      },
      {
        id: 'msg-2',
        role: 'assistant',
        content: '已为你检索到以下相关上下文：',
        timestamp: '2026-05-03T14:32:05',
        contextCards: [
          {
            id: 'ctx-1',
            type: 'knowledge',
            title: 'Redis 连接规范',
            description: '知识库 · 部署 · 数据库 · 最佳实践',
            tags: ['部署', '数据库'],
          },
          {
            id: 'ctx-2',
            type: 'knowledge',
            title: 'AES-256 加密标准',
            description: '知识库 · 安全规范 · 模块',
            tags: ['安全规范'],
          },
          {
            id: 'ctx-3',
            type: 'code',
            title: 'src/utils/redis_client.py',
            description: '代码解析 · 已有 Redis 客户端封装',
            tags: ['代码'],
          },
        ],
        actions: ['生成设计文档', '继续讨论'],
      },
      {
        id: 'msg-3',
        role: 'user',
        content: '生成设计文档',
        timestamp: '2026-05-03T14:33:00',
      },
      {
        id: 'msg-4',
        role: 'assistant',
        content: '📋 IMPLEMENTATION_PLAN.md 已生成',
        timestamp: '2026-05-03T14:33:10',
        specSummary: {
          fileName: 'IMPLEMENTATION_PLAN.md',
          status: 'draft',
          targetFile: 'src/auth/session_manager.py',
          dependencies: ['src/utils/redis_client.py'],
          constraints: ['AES-256 加密 Token，符合安全规范'],
          functionSignatures: [
            'create_session(user_id: str) -> str',
            'get_session(session_id: str) -> dict',
            'delete_session(session_id: str) -> bool',
          ],
          createdAt: '2026-05-03T14:33:10',
        },
        actions: ['查看设计文档', '调度执行', '修改'],
      },
      {
        id: 'msg-5',
        role: 'user',
        content: '确认执行，使用 qwen-code',
        timestamp: '2026-05-03T14:35:00',
      },
      {
        id: 'msg-6',
        role: 'assistant',
        content: '任务执行完成',
        timestamp: '2026-05-03T14:37:00',
        taskStatus: {
          id: 'task-14',
          name: 'Redis 会话管理器',
          status: 'done',
          agent: 'qwen-code',
          elapsed: '2m 30s',
          filesGenerated: 3,
          terminalLines: [
            { text: '$ qwen-code --prompt "..." --workspace ./project', type: 'info' },
            { text: '> Analyzing context...', type: 'info' },
            { text: '> Reading IMPLEMENTATION_PLAN.md...', type: 'info' },
            { text: '> Generating src/auth/session_manager.py ...', type: 'info' },
            { text: '> Generating src/auth/session_schema.py ...', type: 'info' },
            { text: '> Generating tests/test_session.py ...', type: 'info' },
            { text: '> ✅ Done — 3 files generated', type: 'success' },
          ],
          validations: [
            { label: '编译检查通过', passed: true },
            { label: '单元测试通过 (12/12)', passed: true },
            { label: '文件路径匹配', passed: true },
            { label: '函数签名匹配', passed: true },
          ],
        },
      },
    ],
  },
  {
    id: 'session-2',
    title: 'API 设计讨论',
    mode: 'chat',
    status: 'idle',
    createdAt: '2026-05-02T10:00:00',
    updatedAt: '2026-05-02T10:15:00',
    messages: [
      {
        id: 'msg-7',
        role: 'user',
        content: '我们的 RESTful API 应该如何设计版本控制？',
        timestamp: '2026-05-02T10:00:00',
      },
      {
        id: 'msg-8',
        role: 'assistant',
        content: 'RESTful API 版本控制有几种常见方案：\n\n1. **URL 路径版本控制**: `/api/v1/users`\n2. **请求头版本控制**: `Accept: application/vnd.api.v1+json`\n3. **查询参数版本控制**: `/api/users?version=1`\n\n推荐使用 URL 路径方式，直观且易于缓存。',
        timestamp: '2026-05-02T10:00:05',
      },
    ],
  },
  {
    id: 'session-3',
    title: '用户权限中间件',
    mode: 'design',
    status: 'running',
    createdAt: '2026-05-03T15:00:00',
    updatedAt: '2026-05-03T15:05:00',
    messages: [
      {
        id: 'msg-9',
        role: 'user',
        content: '实现一个基于 RBAC 的用户权限中间件',
        timestamp: '2026-05-03T15:00:00',
      },
      {
        id: 'msg-10',
        role: 'assistant',
        content: '正在分析项目中的权限相关代码...',
        timestamp: '2026-05-03T15:00:05',
        taskStatus: {
          id: 'task-15',
          name: '用户权限中间件',
          status: 'running',
          agent: 'qwen-code',
          elapsed: '1m 15s',
          filesGenerated: 0,
          terminalLines: [
            { text: '$ qwen-code --prompt "RBAC middleware" --workspace ./project', type: 'info' },
            { text: '> Analyzing context...', type: 'info' },
            { text: '> Scanning existing auth modules...', type: 'info' },
          ],
          validations: [],
        },
      },
    ],
  },
]

/** 当前模型配置 */
export const mockModelConfig = {
  provider: 'Ollama',
  model: 'qwen2.5-coder:7b',
}

// ==================== 设置配置 Mock 数据 ====================

/** AI 模型配置项 */
export interface ModelConfigItem {
  id: string
  name: string
  provider: 'ollama' | 'openai' | 'lm-studio' | 'custom'
  model: string
  url: string
  type: 'local' | 'cloud'
  status: 'connected' | 'offline' | 'error'
  isDefault: boolean
  temperature?: number
  maxTokens?: number
  latency?: number
}

/** Agent 配置项 */
export interface AgentConfigItem {
  id: string
  name: string
  path: string
  args: string
  status: 'online' | 'offline' | 'not-detected' | 'not-configured'
  version?: string
  isDefault: boolean
}

/** SKILL 配置项 */
export interface SkillConfigItem {
  id: string
  name: string
  description: string
  enabled: boolean
}

/** Mock 模型配置列表 */
export const mockModelConfigs: ModelConfigItem[] = [
  {
    id: 'model-1',
    name: 'Ollama - qwen2.5-coder:7b',
    provider: 'ollama',
    model: 'qwen2.5-coder:7b',
    url: 'http://localhost:11434',
    type: 'local',
    status: 'connected',
    isDefault: true,
    temperature: 0.7,
    maxTokens: 4096,
    latency: 12,
  },
  {
    id: 'model-2',
    name: 'OpenAI - gpt-4o',
    provider: 'openai',
    model: 'gpt-4o',
    url: 'https://api.openai.com',
    type: 'cloud',
    status: 'connected',
    isDefault: false,
    temperature: 0.5,
    maxTokens: 8192,
    latency: 120,
  },
  {
    id: 'model-3',
    name: 'LM-Studio - llama3-8b',
    provider: 'lm-studio',
    model: 'llama3-8b',
    url: 'http://localhost:1234',
    type: 'local',
    status: 'offline',
    isDefault: false,
    temperature: 0.8,
    maxTokens: 4096,
  },
]

/** Mock Agent 配置列表 */
export const mockAgentConfigs: AgentConfigItem[] = [
  {
    id: 'agent-1',
    name: 'qwen-code',
    path: '/usr/local/bin/qwen-code',
    args: '--workspace {project_root}',
    status: 'online',
    version: 'v1.2.3',
    isDefault: true,
  },
  {
    id: 'agent-2',
    name: 'cline',
    path: '~/.cline/bin/cline',
    args: '--mode agent',
    status: 'not-detected',
    isDefault: false,
  },
  {
    id: 'agent-3',
    name: 'opencode',
    path: '',
    args: '',
    status: 'not-configured',
    isDefault: false,
  },
]

/** Mock SKILL 配置列表 */
export const mockSkillConfigs: SkillConfigItem[] = [
  {
    id: 'skill-1',
    name: '严格函数签名校验',
    description: '校验生成代码的函数签名是否与 Spec 定义一致，包括参数类型、返回值',
    enabled: true,
  },
  {
    id: 'skill-2',
    name: '依赖合规检查',
    description: '检查生成代码是否引入未授权的依赖库，确保符合项目依赖规范',
    enabled: true,
  },
  {
    id: 'skill-3',
    name: '安全规范强制',
    description: '强制生成代码符合知识库中定义的安全标准和加密规范',
    enabled: false,
  },
  {
    id: 'skill-4',
    name: '同步生成动画脚本',
    description: '要求 Agent 在实现代码的同时生成对应的动画脚本，用于演示和教学',
    enabled: false,
  },
  {
    id: 'skill-5',
    name: '代码风格检查',
    description: 'ESLint / Prettier / Black 等代码风格规则校验',
    enabled: false,
  },
]

/** 任务级模型绑定 */
export const taskModelBindings: Record<string, string> = {
  'syntax-analysis': 'model-1',
  'function-analysis': 'model-2',
  'ai-chat': 'model-1',
}

/** 任务类型名称映射 */
export const taskTypeLabels: Record<string, { name: string; desc: string }> = {
  'syntax-analysis': { name: '语法结构分析', desc: 'AST 解析、代码结构提取' },
  'function-analysis': { name: '代码功能分析', desc: '业务逻辑理解、功能讲解' },
  'ai-chat': { name: 'AI 问答', desc: '自然语言问答、辅助理解' },
}
