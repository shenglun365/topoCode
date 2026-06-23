/** 任务/后端状态徽章工具 */

export type TaskStatus = 'done' | 'running' | 'pending' | 'modified' | 'error' | 'cancelled' | 'stopping'
export type BackendStatus = 'running' | 'stopped' | 'error'

const TASK_LABELS: Record<TaskStatus, string> = {
  done: '完成',
  running: '运行中',
  pending: '等待中',
  modified: '已修改',
  error: '失败',
  cancelled: '已取消',
  stopping: '正在停止…',
}

const BACKEND_LABELS: Record<BackendStatus, string> = {
  running: '运行中',
  stopped: '已停止',
  error: '异常',
}

const TASK_COLORS: Record<TaskStatus, string> = {
  done: 'var(--success)',
  running: 'var(--accent)',
  pending: 'var(--text-muted)',
  modified: 'var(--warning)',
  error: 'var(--error)',
  cancelled: 'var(--text-muted)',
  stopping: 'var(--warning)',
}

const BACKEND_COLORS: Record<BackendStatus, string> = {
  running: 'var(--success)',
  stopped: 'var(--text-muted)',
  error: 'var(--error)',
}

export function getTaskStatusLabel(status: TaskStatus): string {
  return TASK_LABELS[status] || status
}

export function getTaskStatusColor(status: TaskStatus): string {
  return TASK_COLORS[status] || 'var(--text-muted)'
}

export function getBackendStatusLabel(status: BackendStatus): string {
  return BACKEND_LABELS[status] || status
}

export function getBackendStatusColor(status: BackendStatus): string {
  return BACKEND_COLORS[status] || 'var(--text-muted)'
}

const TASK_BADGE_CLASSES: Record<string, string> = {
  completed: 'badge-success',
  running: 'badge-info',
  queued: 'badge-info',
  error: 'badge-error',
  done: 'badge-success',
  cancelled: 'badge-muted',
  pending: 'badge-muted',
}

export function getTaskStatusBadgeClass(status: string): string {
  return TASK_BADGE_CLASSES[status] || 'badge-muted'
}

const PROJECT_STATUS_BADGE: Record<string, string> = {
  synced: 'badge-green',
  syncing: 'badge-yellow',
  error: 'badge-red',
}

export function getProjectStatusBadge(status: string): string {
  return PROJECT_STATUS_BADGE[status] || 'badge-gray'
}

const PROJECT_STATUS_LABELS: Record<string, string> = {
  synced: 'project.synced',
  syncing: 'project.syncing',
  error: 'common.error',
}

export function getProjectStatusLabelKey(status: string): string {
  return PROJECT_STATUS_LABELS[status] || ''
}
