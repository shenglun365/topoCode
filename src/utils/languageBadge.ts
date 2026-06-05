const LANG_BADGE_MAP: Record<string, string> = {
  TypeScript: 'badge-blue',
  JavaScript: 'badge-yellow',
  Python: 'badge-green',
  Go: 'badge-cyan',
  Rust: 'badge-orange',
  Java: 'badge-red',
  Vue: 'badge-emerald',
  HTML: 'badge-orange',
  C: 'badge-blue',
  'C++': 'badge-purple',
}

export function languageBadge(lang: string): string {
  return LANG_BADGE_MAP[lang] || 'badge-gray'
}
