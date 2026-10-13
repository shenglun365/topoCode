/**
 * 核心资产守护(2610 重构): 规约库 + 挂载关联(挂载即核心, 无分级)。
 *
 * - rules: 规约库(/arch/rule-defs) — 可复用实体, 新建/编辑/删除(级联卸载)
 * - effective: 挂载聚合(/arch/target-rules) — 守护消费同源, ★ 高亮/isCore 判定
 * - targets(): 三层统一联想(/arch/guard-targets)
 */
import { computed, ref } from 'vue'
import { apiDelete, apiGet, apiPost, apiPut } from '@/services/api-client'
import { currentProjectParams } from '@/services/project-service'
import { coreNodeMatcher } from '@/components/assets/coreMarks'

export interface RuleDef {
  id: string
  title: string
  content: string
  source: string
  updatedAt: number
}

export interface EffectiveMark {
  targetType: string
  targetId: string
  title: string
  rulesMd: string
  rules: { ruleId: string; title: string; content: string }[]
}

export interface TargetOption {
  id: string
  title: string
  hint?: string
  type?: string
}

export function useCoreRules() {
  const rules = ref<RuleDef[]>([])
  const effective = ref<EffectiveMark[]>([])
  const loaded = ref(false)
  const loading = ref(false)

  function pid(): string {
    return currentProjectParams().project || ''
  }

  async function refresh(): Promise<void> {
    const p = pid()
    if (!p || loading.value) return
    loading.value = true
    try {
      const [rs, eff] = await Promise.all([
        apiGet<{ items?: RuleDef[] }>(`/arch/rule-defs?project=${encodeURIComponent(p)}`),
        apiGet<{ items?: EffectiveMark[] }>(`/arch/target-rules?project=${encodeURIComponent(p)}`),
      ])
      rules.value = rs?.items ?? []
      effective.value = eff?.items ?? []
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  function isCore(type: string, targetId: string): boolean {
    return effective.value.some((e) => e.targetType === type && e.targetId === targetId)
  }

  function effectiveOf(type: string, targetId: string): EffectiveMark | undefined {
    return effective.value.find((e) => e.targetType === type && e.targetId === targetId)
  }

  /** 图谱高亮匹配器(三层; effective 单源)。 */
  const coreMatcher = computed(() =>
    coreNodeMatcher(effective.value.map((e) => ({ targetType: e.targetType, targetId: e.targetId }))))

  /** 目标冗余标题(资产删除后仍可读; 调用方尽量传现值)。 */
  async function createRule(title: string, content: string, source = 'manual'): Promise<RuleDef> {
    const p = pid()
    if (!p) throw new Error('缺少项目上下文')
    const row = await apiPost<RuleDef>('/arch/rule-defs', { project: p, title, content, source })
    rules.value = [row, ...rules.value]
    return row
  }

  async function updateRule(ruleId: string, patch: { title?: string; content?: string }): Promise<void> {
    const p = pid()
    if (!p) throw new Error('缺少项目上下文')
    const row = await apiPut<RuleDef>(`/arch/rule-defs/${encodeURIComponent(ruleId)}`,
      { project: p, ...patch })
    rules.value = rules.value.map((x) => (x.id === ruleId ? (row as RuleDef) : x))
    await refresh() // effective 内的规约文本同步
  }

  async function deleteRule(ruleId: string): Promise<void> {
    const p = pid()
    if (!p) throw new Error('缺少项目上下文')
    await apiDelete(`/arch/rule-defs/${encodeURIComponent(ruleId)}?project=${encodeURIComponent(p)}`)
    rules.value = rules.value.filter((x) => x.id !== ruleId)
    await refresh() // 级联卸载后 effective 同步
  }

  /** 挂载(幂等)。挂载即核心。 */
  async function attach(type: string, targetId: string, ruleId: string, title = ''): Promise<void> {
    const p = pid()
    if (!p) throw new Error('缺少项目上下文')
    await apiPut('/arch/target-rules', {
      project: p, targetType: type, targetId, ruleId, title: title || targetId,
    })
    await refresh()
  }

  async function detach(type: string, targetId: string, ruleId: string): Promise<void> {
    const p = pid()
    if (!p) throw new Error('缺少项目上下文')
    await apiDelete(
      `/arch/target-rules?project=${encodeURIComponent(p)}&targetType=${encodeURIComponent(type)}`
      + `&targetId=${encodeURIComponent(targetId)}&ruleId=${encodeURIComponent(ruleId)}`)
    await refresh()
  }

  /** 三层统一联想(后端分组独立实现)。 */
  async function targets(type: string, q: string, limit = 8): Promise<TargetOption[]> {
    const p = pid()
    if (!p || !q.trim()) return []
    const d = await apiGet<{ items?: TargetOption[] }>(
      `/arch/guard-targets?project=${encodeURIComponent(p)}&type=${encodeURIComponent(type)}`
      + `&q=${encodeURIComponent(q)}&limit=${limit}`)
    return d?.items ?? []
  }

  /** 手动建语义资产(未提取 ast 节点/跨节点代码段) + 守护接入(ruleIds 挂既有/ruleText 建并挂)。 */
  async function addManualAsset(input: {
    name: string; kind?: string; level?: string; file: string
    startLine?: number; endLine?: number; symbol?: string; desc?: string
    ruleIds?: string[]; ruleText?: string
  }): Promise<{ assetId: string; attached: string[] }> {
    const p = pid()
    if (!p) throw new Error('缺少项目上下文')
    const r = await apiPost<{ asset: { id: string }; attached: string[] }>(
      '/semantic/assets/manual', { project: p, ...input })
    await refresh()
    return { assetId: r.asset.id, attached: r.attached ?? [] }
  }

  return {
    rules, effective, loaded, loading, refresh,
    isCore, effectiveOf, coreMatcher,
    createRule, updateRule, deleteRule, attach, detach, targets, addManualAsset,
  }
}
