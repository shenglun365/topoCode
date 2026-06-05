/** 文件类型颜色映射 */

const FILE_COLORS: Record<string, string> = {
  ts: '#3178c6',
  tsx: '#3178c6',
  js: '#f7df1e',
  jsx: '#f7df1e',
  py: '#3572a5',
  vue: '#42b883',
  css: '#663399',
  scss: '#c6538c',
  html: '#e34f26',
  json: '#292929',
  md: '#083fa1',
  yml: '#cb171e',
  yaml: '#cb171e',
  toml: '#8f5e34',
  go: '#00add8',
  rs: '#dea584',
  java: '#b07219',
  cpp: '#f34b7d',
  c: '#555555',
  h: '#555555',
  swift: '#ffac45',
  rb: '#701516',
  php: '#4f5d95',
  sh: '#89e051',
  sql: '#e38c00',
  dockerfile: '#384d54',
  gitignore: '#e44c30',
}

export function getFileColor(ext: string): string {
  return FILE_COLORS[ext] || 'var(--text-muted)'
}

export function getLanguageLabel(ext: string): string {
  const labels: Record<string, string> = {
    ts: 'TypeScript', tsx: 'TypeScript', js: 'JavaScript', jsx: 'JavaScript',
    py: 'Python', vue: 'Vue', css: 'CSS', scss: 'SCSS', html: 'HTML',
    json: 'JSON', md: 'Markdown', go: 'Go', rs: 'Rust',
    java: 'Java', cpp: 'C++', c: 'C', swift: 'Swift', rb: 'Ruby',
    php: 'PHP', sql: 'SQL', sh: 'Shell', yml: 'YAML', yaml: 'YAML',
  }
  return labels[ext] || ext.toUpperCase()
}
