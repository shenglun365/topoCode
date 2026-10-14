/**
 * 浮卡置顶令牌：代码资产卡 / 逻辑资产卡 共享——点击(含拖拽/拉伸把手)谁谁在最上。
 * 模块级单例(ref)，两卡同域挂载即天然共享，无需 provide。
 */
import { ref } from 'vue'

export type FloatingCard = 'asset' | 'logic'

const topCard = ref<FloatingCard>('asset')

export function bringCardToFront(k: FloatingCard): void {
  topCard.value = k
}

export function isCardTop(k: FloatingCard): boolean {
  return topCard.value === k
}
