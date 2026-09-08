import type { SemanticAssetKind } from '@/types'

/** 语义资产六类的统一色相：全局唯一映射，所有位置(资产列表、基线对比面板、
 * 语义图谱卡、会话引用)的类别标签同色；新增使用场景勿再局部定义。 */
const KIND_COLORS = {
  entity: 'mauve',
  contract: 'yellow',
  state: 'sky',
  rule: 'peach',
  process: 'blue',
  decision: 'green',
} as const

/** chip 背景+文字(无边框)。 */
export const KIND_CHIP_CLASS = Object.fromEntries(
  Object.entries(KIND_COLORS).map(([k, c]) => [k, `bg-ctp-${c}/15 text-ctp-${c}`]),
) as Record<SemanticAssetKind, string>

/** 图谱资产卡变体：chip 色彩 + 同色描边。 */
export const KIND_CARD_CLASS = Object.fromEntries(
  Object.entries(KIND_COLORS).map(([k, c]) => [k, `bg-ctp-${c}/15 text-ctp-${c} border-ctp-${c}/40`]),
) as Record<SemanticAssetKind, string>

export function kindChipClass(kind: string): string {
  return KIND_CHIP_CLASS[kind as SemanticAssetKind] ?? 'bg-ctp-surface0 text-ctp-overlay1'
}
