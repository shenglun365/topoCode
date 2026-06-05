/** 社区 ID 格式化工具 */

export function formatCommunityId(commId: string): string {
  if (!commId) return ''
  if (commId.length <= 8) return commId
  return `${commId.substring(0, 4)}…${commId.substring(commId.length - 4)}`
}

export function formatCommunityLevel(level: string): string {
  const map: Record<string, string> = {
    L1: 'Level 1',
    L2: 'Level 2',
    L3: 'Level 3',
    L4: 'Level 4',
  }
  return map[level] || level
}

export function shortenCommId(id: string, maxLen = 12): string {
  if (!id || id.length <= maxLen) return id
  return `${id.slice(0, 6)}…${id.slice(-4)}`
}
