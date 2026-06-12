/**
 * Extract a compact display label from a community ID.
 * Format: strips redundant prefix parts, keeps level + number suffix.
 * Example: "L0-INCLUDE-342" → "L0-342", "L1-CALL-152" → "L1-152"
 */
export function communityIdLabel(communityId: string): string {
  const parts = communityId.split('-')
  const num = parts[parts.length - 1]
  let level = 'L0'
  for (const p of parts) {
    if (/^L\d+$/i.test(p)) { level = p; break }
  }
  return `${level}-${num}`
}

/**
 * Display label for a community item.
 * Uses AI-generated name if available and distinct from ID,
 * otherwise falls back to compact ID label.
 */
export function communityLabel(item: { communityId: string; name?: string | null }): string {
  if (item.name && item.name !== item.communityId) {
    return item.name.length > 14 ? item.name.slice(0, 14) + '\u2026' : item.name
  }
  return communityIdLabel(item.communityId)
}
