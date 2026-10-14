export type Locale = 'zh-CN' | 'en-US'

export type ReqKind = 'user-story' | 'fr' | 'nfr'
/**
 * 登记簿状态(生命周期重构 v2):
 * draft(规约演进中) | ready(已确认可执行) | done(用户判定阶段性完结) | cancelled
 */

export type SemanticAssetKind = 'entity' | 'contract' | 'state' | 'rule' | 'process' | 'decision'

/** 语义资产抽象粒度(业务→逻辑→实现，越低越贴近代码)。 */
export type SemanticAssetLevel = 'business' | 'logic' | 'implementation'







export interface SemanticAssetDetail {
  fields?: SemanticAssetField[]
  relations?: SemanticAssetRelation[]
  invariants?: string[]
  trigger?: string
  steps?: SemanticAssetStep[]
  branches?: SemanticAssetBranch[]
  /** 动态过程的三段端点：输入/输出(直连其它资产 id 或符号名)。 */
  inputs?: SemanticAssetRelation[]
  outputs?: SemanticAssetRelation[]
  /** state 类别：状态集合与允许迁移(事件驱动)。 */
  states?: SemanticAssetState[]
  transitions?: SemanticAssetTransition[]
  /** rule 类别：配置来源/约束/阈值(仅配置化拆分时)。 */
  configSource?: string
  constraints?: string[]
  thresholds?: { key?: string; value?: string }[]
  /** 横向切面标签(transactional/caching/security/observability/async 等)。 */
  tags?: string[]
  /** business 级聚合：组成该业务概念的下级资产(组合链)。 */
  aggregates?: { assetId: string; name?: string; role?: string }[]
}

/** 静态资产图(entity → 类图，state → 状态图)。 */
export interface AssetDiagramItem {
  assetId: string
  name: string
  type: 'class' | 'state'
  mermaid: string
}

export interface AssetDiagramResult {
  diagrams: AssetDiagramItem[]
}

/** 语义数据资产(architect 自持，来源 codegraph/live)。 */
export interface SemanticAsset {
  id: string
  projectId?: string
  kind: SemanticAssetKind
  /** 抽象粒度 high|medium|low(默认 medium)。 */
  level?: SemanticAssetLevel
  /** H 级聚合资产的下级组合链父级 id。 */
  parentId?: string
  name: string
  desc: string
  /** 关联代码伪码级说明(查询时 LLM 生成，有效生命周期内缓存)。 */
  pseudo?: string
  /** 节点简介(提取时/懒生成：锚点源码 + 术语/规约 → ≤80 字代码级描述)。 */
  nodeBrief?: string
  /** 出边关系描述缓存({from|to 资产id: 证据式描述})。 */
  edgeNotes?: Record<string, { desc?: string; at?: number }>
  detail?: SemanticAssetDetail
  astRefs: AstNodeRef[]
  scopeType?: 'files' | 'symbols' | 'comm' | 'project'
  scopeKey?: string
  source?: 'codegraph' | 'live' | 'kb'
  change?: ChangeType
  status?: 'active' | 'stale' | 'deleted'
  /** 锚定文件哈希签名(文件更新 → 需更新后使用)。 */
  anchorHashes?: Record<string, string>
  /** 稳定规范标识(scope+锚点指纹)。锚点不变 → id 复用，req/plan/task 引用不断链。 */
  canonicalKey?: string
  /** 语义命名变更溯源(锚点不变仅改名)。 */
  renamedFrom?: string
  /** 历史语义名列表。 */
  nameAlias?: string[]
  /** 需更新后使用(文件已变更)。 */
  needsUpdate?: number
  /** 横向切面标签(transactional/caching/security/observability/async 等)。 */
  tags?: string[]
  /** 附加元数据(componentId/scopes 多组件归属等)。 */
  meta?: { componentId?: string; scopes?: string[] }
  deletedAt?: number
  createdAt?: number
  updatedAt?: number
}

/** 语义资产引用(需求/设计/任务/单测贯通)。 */


export interface AssetDetail {
  assetId: string
  name: string
  type: AssetType
  change: ChangeType
  desc: string
  file?: string
  lang?: string
  kind?: ComponentKind
  responsibilities?: string[]
  owns?: string[]
  dependsOn?: string[]
  level?: DataLevel
  invariants?: string[]
  /** 组件选择器元数据：分析类型(依赖分析 INCLUDE / 调用分析 CALL)与层级。 */
  edgeType?: 'INCLUDE' | 'CALL'
  /** 层级(L0/L1)。 */
  hierLevel?: string
  parentId?: string
  parentName?: string
  fileCount?: number
  nodeCount?: number
  edgeCount?: number
  /** 所属分析任务 id(用于拼知识库文档连接)。 */
  taskId?: string
  /** ER 表视图：列 + 关系。 */
  columns?: ErColumn[]
  relations?: ErRelation[]
  /** ORM 视图：实体 ↔ 表。 */
  entity?: string
  table?: string
  ormFields?: OrmField[]
  /** 实体类视图。 */
  entityKind?: EntityClassKind
  fields?: EntityField[]
  methods?: EntityMethod[]
  /** 抽象结构 → AST 节点。 */
  ast?: AstNodeRef
  trigger?: string
  steps?: FlowStep[]
  streams?: DataStream[]
}

export interface Feasibility {
  ok: boolean
  reason: string
  estMin: number
}

/** 需求入池门槛的四维质量评估。 */

export interface RequirementAnalysis {
  functionalScope: string[]      // 功能范围
  entityBoundary: string[]       // 业务实体概念 + 逻辑边界范围
  feasibility: Feasibility
  assetScope: AssetScopeItem[]   // 涉及的数据资产范围(JSON)
  assessment?: RequirementAssessment   // 入池门槛四维评估(可行性/必要性/原子性独立性/可验收性) — agent skills 产出
  assessmentSummary?: string     // 评估综合结论(表单仅记录此结论, MD)
  specsMd?: string               // 规约约束(概要设计产出: 接口契约/兼容性/边界条件, MD)
  implementationPath?: string    // 需求实现路径(汇总报告)
  changes?: ChangeItem[]         // 预计涉及到的修改项(汇总报告)
  steps?: RequirementStep[]      // 具体的执行步骤拆分(汇总报告)
}

/** agent 待回答的问题项(左栏对话的结构化收集回合)。 */

export interface QuestionItem {
  key: string
  label: string
  type: QuestionType
  options?: string[]
  hint?: string
  answer?: string
}

/**
 * 结果表单草案：agent 生成、用户确认后「整份替换」右栏表单。
 * 分片存储：基本信息正文 basicMd(MD)、数据资产 assetScope(JSON)、
 * 质量评估 assessmentSummary(MD)+estMin、规约约束 specsMd(MD)+implementationPath。
 */
export interface FormDraft {
  title: string
  kind: ReqKind
  priority: 'P0' | 'P1' | 'P2'
  /** 类型标签(多维度分类，空格分隔输入 / 弹窗多选)。 */
  tags: string[]
  /** 基本信息正文(MD)：需求描述 + 可验收标准 + 功能范围 + 业务实体边界。 */
  basicMd: string
  /** 涉及的数据资产范围(JSON，限定 id/name/type/role/file 等关联信息)。 */
  assetScope: AssetScopeItem[]
  /** 评估综合结论(MD)。 */
  assessmentSummary: string
  /** 预估耗时(min，结构化，供批次/任务预估)。 */
  estMin: number
  /** 规约约束(MD)。 */
  specsMd: string
  /** 需求实现路径(结构化单行，批次方案直接引用)。 */
  implementationPath: string
  /** agent 完整报告(隐藏载荷，不渲染不编辑；手动起草时为空)。 */
  report?: RequirementAnalysis
}

/** agent 路径建议回合的结论(需求提案 → 分析/直通)。 */

export interface Requirement {
  id: string
  kind: ReqKind
  title: string
  priority: 'P0' | 'P1' | 'P2'
  status: ReqPoolStatus
  /** 当前生效规约版本号(activeVer 指针)。 */
  activeVer?: number
  /** 用户完成判定(RQ 已完成=阶段性完结)。 */
  doneMark?: number
  doneAt?: number
  /** 演进所有权会话(其他会话只读引导)。 */
  ownerConv?: string
  desc: string
  acceptance: string[]
  /** 备注信息(含可验收标准，合并原验收标准字段)。 */
  remarks?: string
  traceTo: string[]
  parentId?: string              // 原始需求 → 分析后需求的拆分血缘(1:N)
  /** 由多条提案分析生成(批量保存)时指向的关联源提案 id(避免重复处理)。 */
  relatedTo?: string[]
  /** 本提案已被并入某条新提案(避免重复处理，分析选择列表中排除)。 */
  mergedInto?: string
  preferredAssetIds?: string[]   // 用户提交时首选的数据资产(source: manual 种子)
  routedBy?: 'analysis' | 'direct'  // 进池路径: 走分析 / 直通
  suggestion?: PathSuggestion       // 提案阶段 agent 的路径建议回合
  analysis?: RequirementAnalysis
  /** 设计方案(方向2)：数据/接口流程/语义层增删改查 + 落地步骤。 */
  design?: RequirementDesign
  planId?: string
  execId?: string                // 所属执行批次(执行会话)
  updatedAt: number
}

// ============ 设计方案(方向2) ============








// ============ 范围圈定(方向1) ============





// ============ 修改前后对比(方向3) ============







export type ChangeType = 'same' | 'added' | 'removed' | 'modified'

export interface ArchComponent {
  id: string
  name: string
  kind: ComponentKind
  desc: string
  lang: string
  change: ChangeType
  parentId?: string
  responsibilities: string[]
  owns: string[]
  dependsOn: string[]
}


// ============ 数据结构：ER 表视图 ============




export interface ErTable {
  id: string
  name: string
  level: DataLevel
  change: ChangeType
  desc: string
  columns: ErColumn[]
  relations: ErRelation[]
  invariants: string[]
  ast: AstNodeRef
}

// ============ 数据结构：ORM 映射视图 ============


export interface OrmMapping {
  id: string
  name: string
  entity: string
  table: string
  level: DataLevel
  change: ChangeType
  desc: string
  fields: OrmField[]
  ast: AstNodeRef
}

// ============ 数据结构：程序内实体类视图 ============




export interface EntityClass {
  id: string
  name: string
  kind: EntityClassKind
  level: DataLevel
  change: ChangeType
  desc: string
  fields: EntityField[]
  methods: EntityMethod[]
  ast: AstNodeRef
}


export interface ExecutionFlow {
  id: string
  name: string
  trigger: string
  change: ChangeType
  desc: string
  steps: FlowStep[]
  /** 时序图视图(≤5 实体，暂定)，表示处理过程。 */
  sequence?: {
    entities: { id: string; name: string; ast?: AstNodeRef }[]
    messages: { id: string; from: string; to: string; label: string }[]
  }
}


export interface DataFlow {
  id: string
  name: string
  desc: string
  change: ChangeType
  streams: DataStream[]
}

export interface ArchitectureModel {
  components: ArchComponent[]
  erTables: ErTable[]
  ormMappings: OrmMapping[]
  entityClasses: EntityClass[]
  executionFlows: ExecutionFlow[]
  dataFlows: DataFlow[]
  codeMappings?: CodeMapping[]
}



export interface GranularityConfig {
  estMinMin: number
  estMinMax: number
  acceptanceMax: number
  p0SubsetMax: number
}





export interface LaunchInfo {
  execRoot: string
  kbRoot: string
  mode: string
  productForm?: string
  scaffold?: Record<string, unknown> | null
}

/** 概览页「agent设置」栏目：KB 关联项(来自 /project/kb/list 的关联项目)。 */
export interface KbConfig {
  dataApiUrl: string
  mcpUrl: string
  lastStatus?: 'unknown' | 'ok' | 'fail'
  lastDetail?: string
  lastCheckAt?: number
  updatedAt?: number
  test?: { status: 'ok' | 'fail'; detail: string }
}

/** 概览页「使用文档」栏目：引导任务。 */
export interface OverviewMission {
  id: string
  title: string
  desc: string
  /** 关联的本地 md 文档 id(点击跳转到 /docs/<docId>)。 */
  docId?: string
}

/** 概览页聚合接口 GET /overview 的返回数据。 */
export interface OverviewData {
  launch: LaunchInfo
  recent: ProjectInfo[]
  kb: {
    count: number
    linked: boolean
    projects: KbProject[]
  }
  kbConfig: KbConfig
  missions: OverviewMission[]
}

/** 宿主目录浏览条目。 */
export interface DirList {
  path: string
  parent: string | null
  readable: boolean
  writable: boolean
  /** 宿主机标识(远程 Web-UI 访问时用于确认目录所在机器)。 */
  host?: {
    name: string
    ip: string
  }
  entries: DirEntry[]
}

/** POST /dir/analyze 返回数据：选定目录的自动识别结果。 */
export interface DirAnalysis {
  root: string
  name: string
  readable: boolean
  writable: boolean
  isGitRoot: boolean
  gitToplevel: string | null
  gitBranch: string | null
  isEmpty: boolean
  hasCode: boolean
  /** 重复打开已建立的 architect 项目(同一 root_path)。 */
  duplicate: {
    id: string
    name: string
    rootPath: string
    mode?: string
  } | null
  /** 可安全关联的有效 KB 项目(同一仓库源校验通过)。 */
  kbCandidates: {
    id: string
    name: string
    rootPath: string
    reason: string
  }[]
}

/** 任务会话统计(依赖三方 agent 接口；可降级为字节量统计)。 */
export interface TaskSessionStats {
  requests: number
  tokensIn: number
  tokensOut: number
  bytesIn: number
  bytesOut: number
}



export type TestLevel = 'L0' | 'L1' | 'L2' | 'L3' | 'L4' | 'L5'

/** 单测执行通道：三方 agent 或 topocode 命令行。 */
export type TestChannel = 'agent' | 'cli'


export interface UnitTest {
  id: string
  name: string
  /** 覆盖的功能模块(知识库组件层级 L0~L5)。 */
  levels: TestLevel[]
  /** 测试脚本路径。 */
  scriptPath: string
  /** 来源：需求流程 / 外部手写 / 自动扫描(预留)。 */
  source: UnitTestSource
  status: UnitTestStatus
  /** 最近一次执行结果。 */
  lastResult?: { passed: number; failed: number; error?: string; note: string; at: number }
  createdAt: number
  updatedAt: number
}

export interface UnitTestSession {
  id: string
  title: string
  channel: TestChannel
  adapter: string
  /** 本会话涉及的单测 id。 */
  testIds: string[]
  status: UnitTestSessionStatus
  messages: AgentMessage[]
  stats?: TaskSessionStats
  createdAt: number
  updatedAt: number
}



export interface AgentMessage {
  id: string
  role: AgentMsgRole
  time: number
  content: string
  tool?: AgentToolCall
}





// ============ 系统管理：LLM 模型配置 ============


export interface ArchLlmModel {
  source: LlmModelSource
  id: string
  name: string
  provider: string
  model: string
  url: string
  type?: string
  isDefault?: boolean
  /** 出站掩码值(******)或空——真值永不回传 FE */
  apiKey?: string
  hasApiKey?: boolean
  updatedAt?: number
}

export interface ArchLlmModelsResult {
  models: ArchLlmModel[]
  imported: number
  manual: number
  modelId: string
}

export interface ArchLlmImportResult {
  models: ArchLlmModel[]
  added: number
  preserved: number
}

export interface Rebaseline {
  status: RebaselineStatus
  baselineId: string
  commit: string
  manifestHash: string
  handshake: { verify: string; verifyOk: boolean; commitResult: string; committedId: string }
}


export interface ExternalCall {
  id: string
  source: string
  tool: string
  method: 'read' | 'write' | 'invoke'
  time: number
  status: ExternalCallStatus
  detail: string
}

export type ProjectMode = 'greenfield' | 'existing'

export type ProductForm = 'ui-ue' | 'io' | 'hybrid'

/** KB 项目(来自 KB project.list，首页路线1 选择源)。 */
export interface KbProject {
  id: string
  name: string
  rootPath: string
  importMode: 'static' | 'git-local' | 'git-remote'
  remoteUrl?: string
  localRepoPath?: string
  sourceCacheDir?: string
  sourceDir?: string
  currentVersionId?: string
  status?: string
  language?: string
  fileCount?: number
  doneTaskCount?: number
  updatedAt?: string
  /** import_mode ∈ {git-local, git-remote} ⇒ 已 git 关联，关联安全。 */
  gitLinked: boolean
  /** current_version_id 非空 ⇒ KB 已有知识基线。 */
  hasBaseline: boolean
  /** matchLevel: /project/kb/match 注入的命中分类(local/remote)，手动条目无。 */
  matchLevel?: 'local' | 'remote'
}

/** 「查找关联」接口返回：按工作目录匹配出的 KB 候选，本地与远程两组同时给出。 */
export interface KbMatchResult {
  workDir: string
  remoteUrl: string
  /** 本地仓库地址命中(主参数)：源码目录/缓存/本地 repo 来源重叠。 */
  local: KbProject[]
  /** 远端一致命中(辅参数)：工作目录 git origin 与 KB 远端相同。 */
  remote: KbProject[]
}

// ============ 需求分析会话历史(临时提案导入) ============

export interface ConversationSummary {
  id: string
  kind?: string
  /** 关联临时提案 id(reqId)；空/未绑定 → 可导入/删除。 */
  reqId?: string
  title: string
  msgCount: number
  preview: string
  createdAt?: number
  updatedAt?: number
}

/** 会话详情 + 消息列表(导入时拉取)。 */
export interface ConversationDetail {
  id: string
  kind?: string
  reqId?: string
  title: string
  messages: ConversationMessage[]
}

export interface ProjectScaffold {
  language: string
  framework?: string
  moduleLayout: 'mono' | 'multi-service' | 'serverless' | 'custom'
  stack?: Record<string, string>
  codestyle?: string
}

export interface ProjectInfo {
  id: string
  name: string
  desc: string
  rootPath: string
  kbRoot?: string
  branch: string
  baselineId: string | null
  baselineCommit: string
  createdAt: number
  active: boolean
  config: GranularityConfig
  mode: ProjectMode
  scaffold?: ProjectScaffold
  productForm?: ProductForm
  /** 已关联 KB 时非空：KB 项目 id / KB 源码目录 / 关联校验时间。 */
  kbProjectId?: string
  kbSourceDir?: string
  linkVerifiedAt?: number
  /** 置顶 / 收藏(近期项目排序：置顶 → 收藏 → 最近更新)。 */
  pinned?: boolean
  favorite?: boolean
}


export interface RepoStatus {
  baseline: RepoBaseline
  head: { commit: string; branch: string; ahead: number }
  diff: {
    filesChanged: number
    added: number
    modified: number
    deleted: number
    deletedHighRisk: boolean
    files: string[]
  }
  lastRebaseline: number | null
}

/** 项目概览(工作区首页)：工作目录/远端/KB/基线 + 相对基线的代码变更与组件变更。 */
export interface ProjectOverviewComponent {
  id: string
  /** KB 组件 name，缺失时后端已回退为组件 id；「未归属」桶为空串 */
  name: string
  parentId: string
  /** 层级深度(根=0)，列表按层级 DFS 先序(父先于子) */
  level: number
  /** 自身独占计数(未被子孙组件覆盖，消重复) */
  added: number
  modified: number
  deleted: number
  /** 自身独占的变更文件清单(叶子=全量，父级=未被子组件覆盖部分) */
  files: string[]
  /** 子树上卷合计(含子孙)，供父组件汇总展示 */
  totalAdded?: number
  totalModified?: number
  totalDeleted?: number
  totalFiles?: number
}

export interface ProjectOverview {
  workDir: string
  /** 仅真实远端 URL(git origin)；本地仓库为空串 */
  remoteUrl: string
  /** 仓库类型：remote=有远端 origin / local=纯本地仓库 */
  repoKind?: 'remote' | 'local'
  branch: string
  defaultBranch: string
  head: { commit: string; branch: string; ahead: number; behind: number; dirty: boolean }
  kb: {
    linked: boolean
    kbProjectId?: string
    kbSourceDir?: string
    kbRoot?: string
    linkVerifiedAt?: number
    /** KB 服务是否可达(null=不可达/旧后端未返回，无法判定) */
    kbReachable?: boolean | null
    /** 绑定的 KB 项目是否仍存在(false=architect 已绑定但 KB 端已删除) */
    kbExists?: boolean | null
    kbProjectName?: string
    /** 基线视图摘要(对外生效任务数/覆盖率/stale；architect 零任务感知) */
    kbView?: { mounted: number; coveragePct: number | null; viewVersion: number; stale: boolean }
  }
  baseline: { id: string | null; commit: string; exists: boolean }
  diff: {
    filesChanged: number
    added: number
    modified: number
    deleted: number
    deletedHighRisk: boolean
    files: ProjectOverviewDiffFile[]
    byComponent: ProjectOverviewComponent[]
  }
}



export interface CodeMapping {
  id: string
  targetType: CodeMappingTarget
  targetId: string
  targetName: string
  file: string
  line: string
  level: DataLevel
  note: string
}

// ============ Greenfield：引导工作流 ============

export type MissionKey =
  | 'product-form' | 'stack' | 'initial-requirements'
  | 'blueprint' | 'scaffold' | 'first-demo'

export interface WorkflowCtx {
  mode: ProjectMode
  productForm?: ProductForm
  scaffoldConfigured: boolean
  poolCount: number
  blueprintConfirmed: boolean
  execRootInitialized: boolean
  baselineCreated: boolean
}

export interface WorkflowMission {
  key: MissionKey
  labelKey: string
  route: string
  completeness: (ctx: WorkflowCtx) => number
  example?: { title: string; content: string }
  recommended?: (ctx: WorkflowCtx) => boolean
}

export interface GuidedWorkflow {
  missions: WorkflowMission[]
  ctx: () => WorkflowCtx
}

/** 图谱文件索引条目(父级按当前图谱 tab 范围预算；>500 资产强制手动圈定)。 */
export interface GraphFileEntry {
  /** 树侧文件路径(首锚点)。 */
  file: string
  /** 源码目录(file 去掉文件名)。 */
  dir: string
  /** 该文件锚定的范围内语义资产数。 */
  n: number
  /** 归属组件 id 列表(componentsOf 口径，首项为主分组)。 */
  comps: string[]
}

/** 会话上下文用量账目(后端 cognition/ctx_usage 回合落账 → conversations.meta.ctxUsage)。 */
export interface CtxUsage {
  /** 本回合实际发送组装体估算 tokens(chars/2 口径)。 */
  used: number
  /** 可用上下文预算 tokens；0=容量未知(模型 API 探测不到，不猜)。 */
  budget: number
  /** 落账时间 epoch ms。 */
  at?: number
}

export interface DirEntry {
  name: string
  isDir: boolean
  size: number
  mtime: number
  readable?: boolean
  writable?: boolean
}

/** GET /dir/list 返回数据。 */

export type AssetType = 'component' | 'er' | 'orm' | 'entity' | 'flow' | 'dataflow'
  | 'asset' | 'process' | 'decision' | 'contract' | 'state' | 'rule'
  | 'data_structure' | 'processing_flow' | 'control_logic'  // 废弃别名(兼容历史数据)

/** 语义数据资产类别：静态·定义(entity/contract/state/rule) × 动态·处理(process/decision)。 */

export interface RequirementAssessment {
  /** 必要性：高 / 中 / 低 */
  necessity: { grade: 'high' | 'medium' | 'low'; reason: string }
  /** 原子性 / 独立性：能否独立交付、与其他需求解耦 */
  atomicity: { independent: boolean; reason: string }
  /** 可验收性：验收标准是否可测试、可验证 */
  acceptability: { ok: boolean; reason: string }
}

/** 分析报告中的具体执行步骤拆分。 */

export interface RequirementStep {
  id: string
  title: string
  desc: string
  estMin: number
  files?: string[]
  context?: string[]
}

export type RebaselineStatus = 'idle' | 'verified' | 'committed'

export interface SemanticAssetBranch {
  condition?: string
  then?: string
  else?: string
  semantic?: string
  symbols?: string[]
  astRefs?: AstNodeRef[]
}

export interface EntityField {
  name: string
  type: string
  visibility: 'public' | 'private' | 'protected'
  desc: string
  ast: AstNodeRef
}

export interface DataStream {
  id: string
  name: string
  from: string
  to: string
  payload: string
  channel: string
  change: ChangeType
}

export type AgentMsgRole = 'user' | 'assistant' | 'tool'

export interface SemanticAssetField {
  name: string
  type?: string
  semantic?: string
}

export interface ChangeItem {
  resource: string     // 改动资源名(组件/数据结构/流程/数据流/文件)
  kind: string         // added / modified / removed
  before: string
  after: string
}

export type UnitTestStatus = 'idle' | 'running' | 'passed' | 'failed' | 'error' | 'skipped'

export interface EntityMethod {
  name: string
  signature: string
  returnType: string
  desc: string
  ast: AstNodeRef
}

export type DataLevel = 'conceptual' | 'logical' | 'physical'

export interface RepoBaseline {
  id: string
  version: string
  commit: string
  manifestHash: string
  createdAt: number
}

export type UnitTestSessionStatus = 'created' | 'running' | 'done' | 'failed' | 'stopped'

/** 单元测试会话：单独保留，可再进入或新建；工作区左右栏执行反馈。 */

export interface FlowStep {
  id: string
  label: string
  owner: string
  type: 'action' | 'decision' | 'io' | 'sync'
  /** 逻辑处理步骤 → AST 节点。 */
  ast?: AstNodeRef
}

export interface ConversationMessage {
  id: string
  conversationId: string
  role: 'user' | 'assistant'
  time: number
  content: string
}

/** 会话历史摘要(历史导入列表条目)。 */

export type EntityClassKind = 'class' | 'struct' | 'value-object' | 'dto'

export interface SemanticAssetTransition {
  from?: string
  to?: string
  event?: string
  condition?: string
  action?: string
}

export type ExternalCallStatus = 'ok' | 'pending' | 'blocked'

export type ReqPoolStatus = 'draft' | 'ready' | 'done' | 'cancelled'

export type UnitTestSource = 'requirement' | 'manual' | 'scan' | 'ai'

/** 单元测试用例(脚本已编写，左栏列表展示；经「添加」关连脚本入库)。 */

export interface AssetScopeItem {
  assetId: string
  assetType: AssetType
  role: 'core' | 'related'   // 核心修改 / 关联修改
  source: 'auto' | 'manual'
  /** 抽象粒度(high|medium|low)：圈定表达"圈的是业务级还是代码级"。 */
  level?: SemanticAssetLevel
  /** 关联到的具体文件(经知识库代码映射对齐)。 */
  file?: string
  /** 核心节点伪代码：标识「改哪里」的范围(业务实体抽象，非详细实现)。 */
  keyNode?: string
}

/** 抽象结构到具体代码 AST 节点的精确定位。 */

export interface OrmField {
  entityField: string
  column: string
  type: string
  tag: string
  desc: string
  ast: AstNodeRef
}

export interface SemanticAssetStep {
  order?: number
  semantic: string
  symbols?: string[]
  astRefs?: AstNodeRef[]
}

export interface ProjectOverviewDiffFile {
  path: string
  status: 'A' | 'M' | 'D' | 'R'
  additions: number
  deletions: number
}

/** 概览页组件变更(按 KB 组件汇总)：counts/files 为本组件+全部子孙的上卷合计。 */

export type LlmModelSource = 'imported' | 'manual'

export type QuestionType = 'text' | 'select' | 'multi-select' | 'assets'

export type ComponentKind = 'gateway' | 'service' | 'infra' | 'storage' | 'integration'
  | 'page' | 'view' | 'widget' | 'ui-module'

export interface SemanticAssetState {
  name: string
  desc?: string
  initial?: boolean
  final?: boolean
}

export interface RequirementDesign {
  dataChanges: DesignDataChange[]
  interfaceChanges: DesignInterfaceChange[]
  semanticChanges: DesignSemanticChange[]
  steps: DesignStep[]
  landingNote: string
  createdAt?: number
}

export interface ErRelation {
  from: string
  to: string
  type: ErRelationType
  key: string
  desc?: string
}

export interface PathSuggestion {
  recommended: 'analyze' | 'direct'
  assessment: string[]           // 评估项: 数据资产规模 / 改动幅度 / 规约影响 / 冲突风险
}

export interface ErColumn {
  name: string
  type: string
  nullable: boolean
  pk?: boolean
  /** 外键 → 目标表 id。 */
  fk?: string
  desc: string
  ast: AstNodeRef
}

export type CodeMappingTarget = 'component' | 'er' | 'orm' | 'entity' | 'flow' | 'dataflow'

export interface AgentToolCall {
  type: AgentToolType
  label: string
  detail: string
  ok?: boolean
}

export interface AstNodeRef {
  file: string
  symbol: string
  kind: AstNodeKind
  startLine: number
  endLine: number
}

/** 知识库资产详情(API 返回的 JSON 形状，覆盖组件/ER 表/ORM 映射/实体类/执行流程/数据流)。 */

export interface SemanticAssetRelation {
  target: string
  type?: string
  semantic?: string
  /** http 契约: 方法清单(GET/POST/...)。 */
  methods?: string[]
  line?: number
}

export type AstNodeKind = 'struct' | 'class' | 'field' | 'method' | 'func' | 'table' | 'column' | 'mapping'

export interface DesignDataChange {
  assetId?: string
  assetType?: string
  action: 'create' | 'alter' | 'drop' | 'extend'
  name?: string
  detail: {
    desc?: string
    columns?: DesignColumn[]
    relations?: DesignRelation[]
  }
}

export interface DesignInterfaceChange {
  assetId?: string
  assetType?: string
  action?: string
  name?: string
  detail?: {
    before?: string
    after?: string
    endpoints?: string[]
    flows?: string[]
  }
  reason?: string
}

export type ErRelationType = '1:1' | '1:N' | 'N:M'

export interface DesignStep {
  title: string
  desc?: string
  estMin?: number
  context?: string[]
}

export type AgentToolType = 'write-file' | 'run-command' | 'run-test'

export interface DesignSemanticChange {
  assetId?: string
  name?: string
  action?: 'create' | 'modify' | 'drop'
  reason?: string
}

export interface DesignColumn {
  name: string
  type: string
  pk?: boolean
  fk?: string
}

export interface DesignRelation {
  from: string
  to: string
  type: string
  key: string
}

/** 工作目录 git 状态轻量探测(概览页初始化卡片; 不依赖 KB 关联)。 */
export interface GitInfoLite {
  isRepo: boolean
  root: string
  branch?: string
  head?: string
  dirty?: boolean
  /** git origin(数据主权批E 迁移自概览「知识库关联」卡的仓库信息行) */
  remoteUrl?: string
  /** 基线设定探测选单: 基线(since)后提交, 最新 10 条(新→旧) */
  log?: GitCommitInfo[]
}

/** git 提交条目(基线锚定选单/提交历史共用形状) */
export interface GitCommitInfo {
  hash: string
  short: string
  author: string
  date: number
  message: string
  isHead?: boolean
}
