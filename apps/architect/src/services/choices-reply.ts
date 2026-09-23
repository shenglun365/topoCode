/**
 * 问询卡回复组装(cv-247) — 纯逻辑单源(组件 ChoicesCard 消费)。
 *
 * 组装规则: 选择题=点选或自定义(输入即覆盖点选); 跳过组显式表达
 * 「跳过（由你决定）」——弃权本身是澄清答案; 全局补充以「——」附尾;
 * 全空 → 空串(调用方禁用发送)。
 */
export interface ChoiceOption { id?: string; label: string; hint?: string; recommended?: boolean }
export interface ChoiceGroup {
  id?: string
  label?: string
  question?: string
  options?: ChoiceOption[]
  required?: boolean
}

export interface ReplyState {
  selections: Record<string, string>
  customs: Record<string, string>
  skipped: Record<string, boolean>
  note: string
}

export const groupKey = (g: ChoiceGroup, i: number): string => String(g.id ?? i + 1)

export function assembleReply(groups: ChoiceGroup[], st: ReplyState): string {
  const parts: string[] = []
  for (const [i, g] of (groups ?? []).entries()) {
    const k = groupKey(g, i)
    const label = g.label || g.question || `问题${i + 1}`
    if (st.skipped[k]) parts.push(`${label}: 跳过（由你决定）`)
    else if (st.customs[k]?.trim()) parts.push(`${label}: ${st.customs[k].trim()}（自定义）`)
    else if (st.selections[k]) {
      const opt = (g.options ?? []).find(
        (o) => (o.id ?? o.label) === st.selections[k])
      if (opt) parts.push(`${label}: ${opt.label}`)
    }
  }
  const note = (st.note ?? '').trim()
  if (note) parts.push(parts.length ? `—— ${note}` : note)
  return parts.join('，')
}

/** 未答的建议项计数(required 且非跳过且无答案)——提示但不硬拦。 */
export function requiredMissing(groups: ChoiceGroup[], st: ReplyState): number {
  return (groups ?? []).filter((g, i) => {
    const k = groupKey(g, i)
    return g.required && !st.skipped[k] && !st.selections[k]
      && !st.customs[k]?.trim()
  }).length
}
