import type { ReqLifecycle } from '@/types'

/** 左栏会话 4 段生命周期(顺序即渲染顺序)。由后端 requirement.status 派生。 */
export const LIFECYCLE_ORDER: ReqLifecycle[] = ['planning', 'ready', 'executing', 'done']

/** lifecycle → i18n labelKey(挂到 requirement.lifecycle.<key>)。 */
export function lifecycleLabelKey(lc: ReqLifecycle): string {
  return lc
}
