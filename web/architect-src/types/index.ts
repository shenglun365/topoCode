export type Locale = 'zh-CN' | 'en-US'

export type ReqKind = 'user-story' | 'fr' | 'nfr'
export type ReqTier = 'raw' | 'analyzed'
/** 需求归属：提案(可继续讨论/再分析) 或 需求池(唯一执行入口)。 */
export type ReqLocation = 'proposal' | 'pool'
export type ReqPoolStatus =
  | 'raw'          // 原始需求：仅描述
  | 'analyzing'    // 分析中
  | 'analyzed'     // 分析后：功能范围/实体边界/优先级已确认
  | 'designed'     // 已被某方案覆盖
  | 'planned'      // 方案已确认，已生成任务方案
  | 'executing'    // 有执行任务在跑
  | 'done'
  | 'cancelled'

export type AssetType = 'component' | 'er' | 'orm' | 'entity' | 'flow' | 'dataflow'

export interface AssetScopeItem {
  assetId: string
  assetType: AssetType
  role: 'core' | 'related'   // 核心修改 / 关联修改
  source: 'auto' | 'manual'
  /** 关联到的具体文件(经知识库代码映射对齐)。 */
  file?: string
  /** 核心节点伪代码：标识「改哪里」的范围(业务实体抽象，非详细实现)。 */
  keyNode?: string
}

/** 抽象结构到具体代码 AST 节点的精确定位。 */
export type AstNodeKind = 'struct' | 'class' | 'field' | 'method' | 'func' | 'table' | 'column' | 'mapping'

export interface AstNodeRef {
  file: string
  symbol: string
  kind: AstNodeKind
  startLine: number
  endLine: number
}

/** 知识库资产详情(API 返回的 JSON 形状，覆盖组件/ER 表/ORM 映射/实体类/执行流程/数据流)。 */
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
export type QuestionType = 'text' | 'select' | 'multi-select' | 'assets'

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
export interface PathSuggestion {
  recommended: 'analyze' | 'direct'
  assessment: string[]           // 评估项: 数据资产规模 / 改动幅度 / 规约影响 / 冲突风险
}

export interface Requirement {
  id: string
  kind: ReqKind
  tier: ReqTier
  /** 归属：提案 / 需求池（提案可携带 analysis，池可移回提案）。 */
  location?: ReqLocation
  title: string
  priority: 'P0' | 'P1' | 'P2'
  status: ReqPoolStatus
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
  planId?: string
  execId?: string                // 所属执行批次(执行会话)
  updatedAt: number
}

export type ComponentKind = 'gateway' | 'service' | 'infra' | 'storage' | 'integration'
  | 'page' | 'view' | 'widget' | 'ui-module'
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

export type DataLevel = 'conceptual' | 'logical' | 'physical'

// ============ 数据结构：ER 表视图 ============

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

export type ErRelationType = '1:1' | '1:N' | 'N:M'

export interface ErRelation {
  from: string
  to: string
  type: ErRelationType
  key: string
  desc?: string
}

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

export interface OrmField {
  entityField: string
  column: string
  type: string
  tag: string
  desc: string
  ast: AstNodeRef
}

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

export type EntityClassKind = 'class' | 'struct' | 'value-object' | 'dto'

export interface EntityField {
  name: string
  type: string
  visibility: 'public' | 'private' | 'protected'
  desc: string
  ast: AstNodeRef
}

export interface EntityMethod {
  name: string
  signature: string
  returnType: string
  desc: string
  ast: AstNodeRef
}

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

export interface FlowStep {
  id: string
  label: string
  owner: string
  type: 'action' | 'decision' | 'io' | 'sync'
  /** 逻辑处理步骤 → AST 节点。 */
  ast?: AstNodeRef
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

export interface DataStream {
  id: string
  name: string
  from: string
  to: string
  payload: string
  channel: string
  change: ChangeType
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
}

export type TaskStatus = 'pending' | 'in-progress' | 'reviewing' | 'done' | 'blocked'
export type TaskKind = 'epic' | 'story' | 'task' | 'check'

export interface TaskNode {
  id: string
  title: string
  kind: TaskKind
  status: TaskStatus
  estMin: number
  context: string[]
  files: string[]
  children?: TaskNode[]
}

export interface GranularityConfig {
  estMinMin: number
  estMinMax: number
  acceptanceMax: number
  p0SubsetMax: number
}

export type DesignPlanStatus = 'draft' | 'confirmed'

export interface ChangeItem {
  resource: string     // 改动资源名(组件/数据结构/流程/数据流/文件)
  kind: string         // added / modified / removed
  before: string
  after: string
}

export interface PlanImpact {
  affected: string[]   // 受影响组件
  grade: string
  basis: string
  risks: string[]
}

export interface DesignPlan {
  id: string
  reqIds: string[]
  title: string
  approach: string
  changes: ChangeItem[]
  impact: PlanImpact
  status: DesignPlanStatus
  taskPlanId?: string
  baseCommit: string
  updatedAt: number
}

export type ExecutionStatus = 'created' | 'running' | 'accepting' | 'done' | 'failed' | 'blocked' | 'stopped'
export type Connectivity = 'unknown' | 'ok' | 'fail'

/** 任务会话统计(依赖三方 agent 接口；可降级为字节量统计)。 */
export interface TaskSessionStats {
  requests: number
  tokensIn: number
  tokensOut: number
  bytesIn: number
  bytesOut: number
}

export type AppendedReqStatus = 'appending' | 'analyzed' | 'designed' | 'executing' | 'done'

export interface AppendedReq {
  id: string
  title: string
  desc: string
  scope: string[]
  analysis?: RequirementAnalysis
  design?: { approach: string; changes: ChangeItem[] }
  status: AppendedReqStatus
  updatedAt: number
}

export interface ExecutionTask {
  id: string
  planId: string
  adapter: string
  /** coding agent 模型参数(三方 agent 仅切换模型时生效)。 */
  model?: string
  /** 本任务覆盖的需求池项 id 集合。 */
  reqIds: string[]
  connectivity: Connectivity
  status: ExecutionStatus
  sessionIds: string[]
  baseCommit: string
  runCount: number
  createdAt: number
  updatedAt?: number
  endedAt?: number
  error?: string
  /** 任务树重建次数(任务树随执行过程变化时递增)。 */
  treeRevision?: number
  /** 会话统计。 */
  stats?: TaskSessionStats
  amendments: AppendedReq[]
}

export type AgentStatus = 'idle' | 'planning' | 'working' | 'testing' | 'done' | 'failed' | 'stopped'
export type AgentMsgRole = 'user' | 'assistant' | 'tool'
export type AgentToolType = 'write-file' | 'run-command' | 'run-test'

export interface AgentToolCall {
  type: AgentToolType
  label: string
  detail: string
  ok?: boolean
}

export interface AgentMessage {
  id: string
  role: AgentMsgRole
  time: number
  content: string
  tool?: AgentToolCall
}

export interface AgentSession {
  id: string
  taskId: string
  adapter: string
  status: AgentStatus
  messages: AgentMessage[]
  keepContext: boolean
  artifacts: string[]
  testResult?: { passed: number; failed: number; note: string }
  stats?: TaskSessionStats
}

export interface Snapshot {
  id: string
  name: string
  version: string
  createdAt: number
  model: ArchitectureModel
}

export type WorkflowStageKey = 'pool' | 'design' | 'execute' | 'accept'

export type StepStatus = 'locked' | 'pending' | 'active' | 'done'

export interface WorkflowStageRoute {
  path: string
  query?: Record<string, string>
}

/** 数据快照，供阶段定义(数据对象)中的 isDone/matches 谓词做判定。 */
export interface WorkflowStageCtx {
  proposalCount: number          // 需求提案(未分析)
  poolCount: number              // 需求池(已分析待执行)
  analyzedCount: number
  confirmedPlanCount: number
  activeTaskCount: number
  acceptingCount: number
  doneTaskCount: number
}

/** 单个流水线阶段的声明式定义，未来微调只改这里/配置数据对象。 */
export interface WorkflowStageDef {
  key: WorkflowStageKey
  /** i18n key 后缀，挂到 workflow.steps.<labelKey> */
  labelKey: string
  route: WorkflowStageRoute
  /** 当前路由/查询 + 数据快照是否命中本阶段(决定 stepper 高亮)。 */
  matches: (ctx: WorkflowStageCtx, path: string, query?: Record<string, unknown>) => boolean
  /** 该阶段工作是否已完成(决定 stepper 的 done/locked)。 */
  isDone: (ctx: WorkflowStageCtx) => boolean
}

export interface WorkflowStep {
  key: WorkflowStageKey
  labelKey: string
  status: StepStatus
  route: WorkflowStageRoute
}

export type SpecLayerKind = 'override' | 'explicit' | 'derived'

export interface SpecOverride {
  file: string
  communityKey: string
  pinned: boolean
  note: string
}

export interface SpecRule {
  id: string
  text: string
  level: 'blocker' | 'major' | 'minor'
  source: SpecLayerKind
}

export interface SpecChangeEntry {
  version: string
  date: number
  note: string
  confirmedBy: string
}

export interface ArchitectureSpec {
  version: string
  overrides: SpecOverride[]
  explicitRules: SpecRule[]
  derivedRules: SpecRule[]
  changelog: SpecChangeEntry[]
}

export type DiffGrade = 'S' | 'M' | 'L'

export interface StagingLayerStatus {
  file: { reParsed: number; reusedByHash: number; edgesChanged: number }
  community: { refined: number; dirty: number; action: string }
  semantic: { reExplained: number; dirty: number; inherited: number }
}

export interface StagingModel {
  scope: { filesChanged: string[]; added: number; modified: number; deleted: number; deletedHighRisk: boolean }
  grade: DiffGrade
  gradeBasis: string
  gradeAction: string
  affectedComponents: string[]
  layers: StagingLayerStatus
}

export interface IncrementalLogEntry {
  id: string
  time: number
  scope: string
  grade: DiffGrade
  files: string[]
  edgesChanged: number
  reExplained: string[]
  boundaryChanged: string[]
}

export type ComplianceKind = 'boundary' | 'spec' | 'critical' | 'direction'

export interface ComplianceCheck {
  id: string
  name: string
  kind: ComplianceKind
  pass: boolean
  level: 'blocker' | 'major' | 'minor'
  detail: string
  scope: string
}

export type GateKey = 'codeMerge' | 'specChange' | 'baselineCreate'
export type RebaselineStatus = 'idle' | 'verified' | 'committed'

export interface Rebaseline {
  status: RebaselineStatus
  baselineId: string
  commit: string
  manifestHash: string
  handshake: { verify: string; verifyOk: boolean; commitResult: string; committedId: string }
}

export type ExternalCallStatus = 'ok' | 'pending' | 'blocked'

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
}

export interface RepoBaseline {
  id: string
  version: string
  commit: string
  manifestHash: string
  createdAt: number
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

export type CollabMode = 'main-agent' | 'mcp-server' | 'spec-assist' | 'migration'

export type CodeMappingTarget = 'component' | 'er' | 'orm' | 'entity' | 'flow' | 'dataflow'

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

// ============ 系统基线：概要信息 ============

/** 系统基线概要信息(顶部可折叠信息栏)。 */
export interface BaselineInfo {
  gitTag: string
  branch: string
  gitDate: number
  analyzedAt: number
  archVersion: string
  commit: string
  desc: string
}

// ============ 系统基线：知识库复合查询 ============

export type KbQueryRelKind = 'depends' | 'calls'   // 依赖组件 / 被调用组件
export type KbQuerySection = 'basic' | 'structure' | 'flow'

/** 复合查询条件(用户输入)。 */
export interface KbQuerySpec {
  kind: KbQueryRelKind
  compIds: string[]
  sections: KbQuerySection[]
  /** 简短补充描述。 */
  note?: string
}

/** 单条查询调用的知识库 skill 记录。 */
export interface KbQuerySkill {
  name: string
  detail: string
}

/** 单个组件的分析结果(MD 片段)。 */
export interface KbQueryCompResult {
  componentId: string
  name: string
  kind: string
  /** 关联组件(依赖/被调用)解析后的聚合 MD。 */
  relMd: string
  basicMd: string
  structureMd: string
  flowMd: string
}

export interface KbQueryResult {
  id: string
  spec: KbQuerySpec
  /** 本次查询调用的知识库 skill 集合。 */
  skills: KbQuerySkill[]
  summary: string
  compResults: KbQueryCompResult[]
  cached: boolean
  baselineTag: string
  createdAt: number
}

/** 复合查询历史(聚合成信息流)。 */
export interface KbQueryHistory {
  id: string
  spec: KbQuerySpec
  baselineTag: string
  cached: boolean
  createdAt: number
  summary: string
}

export type InteractionKind = 'issue' | 'info' | 'choice'
export type InteractionStatus = 'pending' | 'resolved'

export interface UserInteraction {
  id: string
  kind: InteractionKind
  taskId: string
  prompt: string
  options?: string[]
  answer?: string
  status: InteractionStatus
  createdAt: number
}

// ============ Greenfield：架构蓝图 ============

export interface Blueprint {
  id: string
  title: string
  description: string
  model: ArchitectureModel
  designTreeRootId?: string
  source: 'agent-draft' | 'user' | 'agent+user'
  status: 'draft' | 'confirmed'
  createdAt: number
  confirmedAt?: number
}

// ============ Greenfield：DesignTree 递归细化 ============

export type DesignTreeNodeKind = 'service' | 'page' | 'entity' | 'flow' | 'sub'
export type DesignTreeNodeStatus = 'pending' | 'locked' | 'demo-freeze'

export interface DesignTreeNode {
  id: string
  parentId?: string
  what: string
  how: string
  howDetail: string
  kind: DesignTreeNodeKind
  status: DesignTreeNodeStatus
  children: DesignTreeNode[]
  exampleRef?: string
}

// ============ Greenfield：脚手架 ============

export type ScaffoldLayer = 1 | 2 | 3 | 4 | 5 | 6

export interface ScaffoldFile {
  path: string
  action: 'create' | 'modify' | 'skip'
  summary: string
}

export interface ScaffoldResult {
  token: string
  files: ScaffoldFile[]
  validation: { build: boolean; vet: boolean; test: boolean }
}

export interface ScaffoldConfirm {
  commit: string
  filesWritten: number
  buildPass: boolean
}

// ============ Greenfield：抽取（knowledge base bootstrap） ============

export interface ExtractConfig {
  execRoot: string
  kbRoot: string
  commit: string
  baselineVersion: string
}

export interface ExtractResult {
  snapshotId: string
  model: ArchitectureModel
  mappings: CodeMapping[]
  metrics: { components: number; entities: number; flows: number; mappings: number }
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
