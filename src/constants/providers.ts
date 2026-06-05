/** AI Provider 默认 URL 常量 */

export const PROVIDER_DEFAULT_URLS: Record<string, string> = {
  ollama: 'http://localhost:11434',
  'lm-studio': 'http://localhost:1234',
  openai: 'https://api.openai.com/v1',
  deepseek: 'https://api.deepseek.com',
  'minimax-cn': 'https://api.minimax.chat/v1',
  'minimax-global': 'https://api.minimax.com/v1',
  openrouter: 'https://openrouter.ai/api/v1',
}

export const PROVIDER_NAMES: Record<string, string> = {
  ollama: 'Ollama',
  'lm-studio': 'LM Studio',
  openai: 'OpenAI',
  deepseek: 'DeepSeek',
  'minimax-cn': 'MiniMax (CN)',
  'minimax-global': 'MiniMax (Global)',
  openrouter: 'OpenRouter',
}

export const CDN_URLS = {
  D3: 'https://cdn.jsdelivr.net/npm/d3@7',
  TOPO_ANIMATION: 'https://cdn.jsdelivr.net/npm/@topocode/topo-animation@latest/dist/index.umd.js',
  PLANTUML_RENDER: 'http://www.plantuml.com/plantuml',
}

export const GITHUB_URL = 'https://github.com/shenglun365/topoCode'
