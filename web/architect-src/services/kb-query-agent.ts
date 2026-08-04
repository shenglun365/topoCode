import type { ArchComponent, KbQueryCompResult, KbQueryResult, KbQuerySection, KbQuerySkill, KbQuerySpec } from '@/types'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { useArchMcpStore } from '@/stores/mcp-store'
import { currentBaselineInfo } from './baseline-service'

/**
 * 知识库复合查询 agent —— 系统基线工作区专用。
 *
 * 报表式查询：以「组件 → 依赖/被调用组件」为轴，按需展开基本信息 / 核心数据结构 / 核心流程，
 * 每次查询调用一组知识库 skill 提供专项能力；命中条件缓存由基线变更驱动失效。
 *
 * 原型阶段全部为 mock 实现：以架构资产(组件/数据结构/流程)充当知识库检索源。
 */
export interface KbAgentOptions {
  /** 命中缓存时由调用方标记，走缓存旁路。 */
  cached?: boolean
}

function resolveComponents(ids: string[]): ArchComponent[] {
  const arch = useArchArchitectureStore()
  return ids
    .map((id) => arch.components.find((c) => c.id === id || c.name === id))
    .filter((c): c is ArchComponent => !!c)
}

/** 依赖组件：目标组件直接依赖的下游组件。 */
function dependsOn(target: ArchComponent): ArchComponent[] {
  return resolveComponents(target.dependsOn)
}

/** 被调用组件：反向检索——谁依赖了目标组件。 */
function calledBy(target: ArchComponent): ArchComponent[] {
  const arch = useArchArchitectureStore()
  return arch.components.filter((c) => c.id !== target.id && c.dependsOn.includes(target.id))
}

const kindLabel: Record<string, string> = {
  gateway: '网关',
  service: '服务',
  infra: '基础设施',
  storage: '存储',
  integration: '集成',
}

function relMd(rels: ArchComponent[], kind: KbQuerySpec['kind']): string {
  const title = kind === 'depends' ? '依赖组件' : '被调用组件'
  if (!rels.length) return `## ${title}\n\n无${title}。\n`
  return `## ${title}\n\n${rels.map((r) => `- **${r.name}** (${kindLabel[r.kind] ?? r.kind}) — ${r.desc}`).join('\n')}\n`
}

function basicMd(comp: ArchComponent): string {
  return `## 基本信息\n\n- 名称: **${comp.name}**\n- 类型: ${kindLabel[comp.kind] ?? comp.kind}\n- 语言: ${comp.lang}\n- 变更: ${comp.change}\n\n${comp.desc}\n\n职责: ${comp.responsibilities.join('、')}`
}

function structureMd(comp: ArchComponent): string {
  const arch = useArchArchitectureStore()
  const owned = comp.owns.map((id) => arch.erTables.find((t) => t.id === id) ?? arch.ormMappings.find((m) => m.id === id) ?? arch.entityClasses.find((e) => e.id === id))
  const rows = owned.filter((x): x is NonNullable<typeof x> => !!x)
  if (!rows.length) return '## 核心数据结构\n\n无。\n'
  return `## 核心数据结构\n\n${rows.map((x) => {
    const ast = x.ast ? ` \`${x.ast.file} L${x.ast.startLine}\`` : ''
    return `- **${x.name}** — ${x.desc}${ast}`
  }).join('\n')}\n`
}

function flowMd(comp: ArchComponent): string {
  const arch = useArchArchitectureStore()
  const flows = arch.executionFlows.filter((f) => f.steps.some((s) => s.owner === comp.name))
  if (!flows.length) return '## 核心流程\n\n无。\n'
  return `## 核心流程\n\n${flows.map((f) => `- **${f.name}** (${f.trigger}) — ${f.desc}`).join('\n')}\n`
}

/** 依据查询条件选取知识库 skill 集合。 */
function selectSkills(spec: KbQuerySpec): KbQuerySkill[] {
  const skills: KbQuerySkill[] = [
    { name: 'kb.graph', detail: `按「${spec.kind === 'depends' ? '依赖' : '被调用'}」遍历组件依赖图` },
  ]
  if (spec.sections.includes('basic')) skills.push({ name: 'kb.component.info', detail: '读取组件基本信息(职责/语言/变更)' })
  if (spec.sections.includes('structure')) skills.push({ name: 'kb.structure.read', detail: '检索组件拥有的核心数据结构(ER/ORM/实体)' })
  if (spec.sections.includes('flow')) skills.push({ name: 'kb.flow.read', detail: '检索组件参与的核心流程' })
  return skills
}

function buildCompResult(target: ArchComponent, spec: KbQuerySpec): KbQueryCompResult {
  const rels = spec.kind === 'depends' ? dependsOn(target) : calledBy(target)
  const sections: KbQuerySection[] = spec.sections
  return {
    componentId: target.id,
    name: target.name,
    kind: target.kind,
    relMd: relMd(rels, spec.kind),
    basicMd: sections.includes('basic') ? basicMd(target) : '',
    structureMd: sections.includes('structure') ? structureMd(target) : '',
    flowMd: sections.includes('flow') ? flowMd(target) : '',
  }
}

function buildSummary(spec: KbQuerySpec, compResults: KbQueryCompResult[], skills: KbQuerySkill[]): string {
  const names = compResults.map((c) => c.name).join('、')
  const relWord = spec.kind === 'depends' ? '依赖' : '被调用'
  const skillsWord = skills.map((s) => s.name).join(', ')
  return `基于知识库对「${names}」执行${relWord}关系分析：覆盖 ${compResults.length} 个组件，调用 skill [${skillsWord}]。`
}

export const kbQueryAgent = {
  /** 执行一次知识库复合查询。 */
  async query(spec: KbQuerySpec, opts: KbAgentOptions = {}): Promise<KbQueryResult> {
    const targets = resolveComponents(spec.compIds)
    const skills = selectSkills(spec)
    const compResults = targets.map((t) => buildCompResult(t, spec))
    const baseline = currentBaselineInfo()
    const result: KbQueryResult = {
      id: `kq-${Date.now()}`,
      spec,
      skills,
      summary: buildSummary(spec, compResults, skills),
      compResults,
      cached: opts.cached ?? false,
      baselineTag: baseline.gitTag,
      createdAt: Date.now(),
    }
    this.record('topocode.kb.query', `复合查询: ${spec.kind === 'depends' ? '依赖' : '被调用'} · ${compResults.length} 组件 · skill ${skills.length}`)
    return result
  },

  /** 判定缓存命中：基于输入条件生成稳定 key。 */
  cacheKey(spec: KbQuerySpec): string {
    return [
      spec.kind,
      [...spec.compIds].sort().join(','),
      [...spec.sections].sort().join(','),
      (spec.note ?? '').trim(),
    ].join('|')
  },

  record(tool: string, detail: string) {
    const mcp = useArchMcpStore()
    mcp.record({
      id: `kbq-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      source: 'topocode-kb',
      tool,
      method: 'invoke',
      time: Date.now(),
      status: 'ok',
      detail,
    })
  },
}
