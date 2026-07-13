<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ipc } from '@/services/ipc'
import { ChevronDownIcon, ChevronRightIcon } from '@heroicons/vue/24/outline'

const { t, locale } = useI18n()

const USE_MOCK = import.meta.env.DEV && !import.meta.env.VITE_DISABLE_MOCK

const CHAT_TOOLS_ZH = [
  { name: 'get_file_content', description: '获取指定源码文件的完整内容（超过 10000 字符自动截断）', parameters: { fileId: '文件唯一标识', filePath: '文件相对路径（与 fileId 二选一）' } },
  { name: 'get_symbol_detail', description: '获取指定符号的详细信息：类型、签名、代码片段、所在文件路径', parameters: { symbolId: '符号唯一标识 ID' } },
  { name: 'get_community_subgraph', description: '获取社区子图结构：包含指定社区内的所有节点和边，支持按深度展开', parameters: { taskId: '分析任务 ID', commId: '社区分组 ID', edgeType: '边类型 (CALL/DEPENDENCY)' } },
  { name: 'get_edge_detail', description: '获取边的详细信息：调用关系、依赖类型、数据流方向', parameters: { edgeId: '边的唯一标识 ID' } },
  { name: 'search_symbols', description: '按名称搜索项目中的符号（函数/类/方法/变量），返回匹配列表', parameters: { query: '搜索关键词', limit: '最多返回条数' } },
  { name: 'get_call_chain', description: '获取两个符号之间的调用链路（含中间节点），支持限制最大深度', parameters: { fromSymbolId: '起始符号 ID', toSymbolId: '目标符号 ID', taskId: '分析任务 ID', maxDepth: '最大深度' } },
  { name: 'get_ast_node', description: '获取指定 AST 节点的详细代码内容（含所在文件和行号范围）', parameters: { nodeId: 'AST 节点 ID', fileId: '文件 ID' } },
]

const CHAT_TOOLS_EN = [
  { name: 'get_file_content', description: 'Get full content of specified source file (auto-truncated beyond 10000 chars)', parameters: { fileId: 'File unique ID', filePath: 'File relative path (alternative to fileId)' } },
  { name: 'get_symbol_detail', description: 'Get detailed symbol info: type, signature, code snippet, file path', parameters: { symbolId: 'Symbol unique ID' } },
  { name: 'get_community_subgraph', description: 'Get community subgraph structure: all nodes and edges, supports depth expansion', parameters: { taskId: 'Analysis task ID', commId: 'Community group ID', edgeType: 'Edge type (CALL/DEPENDENCY)' } },
  { name: 'get_edge_detail', description: 'Get detailed edge info: call relations, dependency type, data flow direction', parameters: { edgeId: 'Edge unique ID' } },
  { name: 'search_symbols', description: 'Search project symbols by name (functions/classes/methods/variables), returns matching list', parameters: { query: 'Search keyword', limit: 'Max results' } },
  { name: 'get_call_chain', description: 'Get call chain between two symbols (including intermediate nodes), supports max depth', parameters: { fromSymbolId: 'Start symbol ID', toSymbolId: 'Target symbol ID', taskId: 'Analysis task ID', maxDepth: 'Max depth' } },
  { name: 'get_ast_node', description: 'Get AST node source code (with file path and line range)', parameters: { nodeId: 'AST node ID', fileId: 'File ID' } },
]

const MOCK_AGENT_CONFIG = {
  routes: [
    { action: 'overview', workflow: 'OverviewWorkflow', description: 'Generate overall architecture overview document. Agent reads community analysis results, file pre-summaries, source files etc., outputs architecture overview Markdown.' },
    { action: 'analyze_components', workflow: 'AgenticComponentAnalystWorkflow', description: 'Agent multi-turn component analysis, LLM autonomously calls read_file / search_content etc. to read files then analyze.' },
    { action: 'presummary_files', workflow: 'PreSummaryWorkflow', description: 'File pre-summary batch cache — read, summarize and cache files before analysis.' },
  ],
  skills: [
    { name: 'skill_generate_arch_overview', description: 'Generate architecture overview', steps: 3 },
    { name: 'skill_analyze_community', description: 'Analyze a community in depth', steps: 4 },
    { name: 'skill_read_source_file', description: 'Read source file content', steps: 1 },
    { name: 'skill_search_symbols', description: 'Search code symbols by name', steps: 1 },
    { name: 'skill_explore_graph', description: 'Explore community subgraph', steps: 1 },
    { name: 'skill_analyze_relations', description: 'Analyze code relations', steps: 1 },
    { name: 'skill_batch_analyze_communities', description: 'Batch analyze communities', steps: 5 },
  ],
  tools: [],
}

const TOOLS_ZH = [
  { name: 'read_file', description: '读取源码文件内容', category: 'file', llm_visible: true },
  { name: 'search_content', description: '按模式搜索文件内容', category: 'file', llm_visible: true },
  { name: 'summarize_file', description: '通过 LLM 摘要文件内容', category: 'file', llm_visible: true },
  { name: 'get_symbol_detail', description: '获取符号详细信息（类型、签名、代码片段）', category: 'symbol', llm_visible: true },
  { name: 'search_symbols', description: '按名称搜索符号', category: 'symbol', llm_visible: true },
  { name: 'get_symbol_code', description: '获取符号源码', category: 'symbol', llm_visible: true },
  { name: 'get_community_subgraph', description: '获取社区子图结构', category: 'graph', llm_visible: true },
  { name: 'get_call_chain', description: '获取调用链路图', category: 'graph', llm_visible: true },
  { name: 'get_ast_node', description: '获取 AST 节点详情', category: 'graph', llm_visible: true },
  { name: 'get_edge_detail', description: '获取边详情', category: 'edge', llm_visible: true },
]

const TOOLS_EN = [
  { name: 'read_file', description: 'Read source file content', category: 'file', llm_visible: true },
  { name: 'search_content', description: 'Search file content by pattern', category: 'file', llm_visible: true },
  { name: 'summarize_file', description: 'Summarize file via LLM', category: 'file', llm_visible: true },
  { name: 'get_symbol_detail', description: 'Get symbol details', category: 'symbol', llm_visible: true },
  { name: 'search_symbols', description: 'Search symbols by name', category: 'symbol', llm_visible: true },
  { name: 'get_symbol_code', description: 'Get symbol source code', category: 'symbol', llm_visible: true },
  { name: 'get_community_subgraph', description: 'Get community subgraph', category: 'graph', llm_visible: true },
  { name: 'get_call_chain', description: 'Get call chain graph', category: 'graph', llm_visible: true },
  { name: 'get_ast_node', description: 'Get AST node details', category: 'graph', llm_visible: true },
  { name: 'get_edge_detail', description: 'Get edge details', category: 'edge', llm_visible: true },
]

const activeSubTab = ref<'routes' | 'skills' | 'tools' | 'chat'>('routes')
const rawConfig = ref<{ routes: any[]; skills: any[]; tools: any[] }>({ routes: [], skills: [], tools: [] })
const loading = ref(true)
const error = ref('')
const search = ref('')
const expanded = ref<Record<string, boolean>>({})

const config = computed(() => {
  const isZh = locale.value?.startsWith('zh')
  const base = rawConfig.value
  return {
    routes: base.routes.length ? base.routes : MOCK_AGENT_CONFIG.routes,
    skills: base.skills.length ? base.skills : MOCK_AGENT_CONFIG.skills,
    tools: isZh ? TOOLS_ZH : TOOLS_EN,
  }
})

const chatTools = computed(() => {
  return locale.value?.startsWith('zh') ? CHAT_TOOLS_ZH : CHAT_TOOLS_EN
})

onMounted(async () => {
  if (USE_MOCK) {
    loading.value = false
    return
  }
  try {
    rawConfig.value = await ipc.analysis.getAgentConfig()
  } catch (e: any) {
    console.warn('[AgentConfig] API failed, using mock data:', e)
  } finally {
    loading.value = false
  }
})

const tabs = [
  { key: 'routes' as const, label: () => t('settings.agent.tabRoutes'), count: () => config.value.routes.length },
  { key: 'skills' as const, label: () => t('settings.agent.tabSkills'), count: () => config.value.skills.length },
  { key: 'tools' as const, label: () => t('settings.agent.tabTools'), count: () => config.value.tools.length },
]

const routeTemplateMap: Record<string, string[]> = {
  overview: ['agent_generate_overview', 'report_overall_architecture'],
  analyze_components: ['agent_analyze_component'],
}

const filteredRoutes = computed(() => {
  const q = search.value.toLowerCase()
  if (!q) return config.value.routes
  return config.value.routes.filter(r =>
    (r.action || '').toLowerCase().includes(q) ||
    (r.workflow || '').toLowerCase().includes(q) ||
    (r.description || '').toLowerCase().includes(q)
  )
})

const filteredSkills = computed(() => {
  const q = search.value.toLowerCase()
  if (!q) return config.value.skills
  return config.value.skills.filter(s =>
    (s.name || '').toLowerCase().includes(q) ||
    (s.description || '').toLowerCase().includes(q)
  )
})

const filteredTools = computed(() => {
  const q = search.value.toLowerCase()
  if (!q) return config.value.tools
  return config.value.tools.filter(t =>
    (t.name || '').toLowerCase().includes(q) ||
    (t.category || '').toLowerCase().includes(q) ||
    (t.description || '').toLowerCase().includes(q)
  )
})

const filteredChatTools = computed(() => {
  const q = search.value.toLowerCase()
  if (!q) return chatTools.value
  return chatTools.value.filter(t =>
    (t.name || '').toLowerCase().includes(q) ||
    (t.description || '').toLowerCase().includes(q)
  )
})

function toggleExpand(key: string) {
  expanded.value[key] = !expanded.value[key]
}

function itemJson(obj: any): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}
</script>

<template>
  <div class="agcfg-container">
    <div class="agcfg-intro">
      {{ t('settings.agent.intro') }}
    </div>
    <div class="agcfg-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="agcfg-tab"
        :class="{ active: activeSubTab === tab.key }"
        @click="activeSubTab = tab.key"
      >
        {{ tab.label() }} ({{ tab.count() }})
      </button>
      <span class="agcfg-tab-sep">|</span>
      <button
        class="agcfg-tab"
        :class="{ active: activeSubTab === 'chat' }"
        @click="activeSubTab = 'chat'"
      >
        {{ t('settings.agent.tabChat') }} ({{ chatTools.length }})
      </button>
    </div>

    <div class="agcfg-search">
      <input
        v-model="search"
        class="input agcfg-search-input"
        :placeholder="t('common.search') + '...'"
      >
    </div>

    <div
      v-if="loading"
      class="agcfg-loading"
    >
      {{ t('common.loading') }}
    </div>
    <div
      v-else-if="error"
      class="agcfg-error"
    >
      {{ error }}
    </div>

    <div v-else>
      <!-- Routes -->
      <div
        v-show="activeSubTab === 'routes'"
        class="agcfg-list"
      >
        <div
          v-for="r in filteredRoutes"
          :key="r.action"
          class="agcfg-item"
        >
          <div
            class="agcfg-item-header"
            @click="toggleExpand('route-' + r.action)"
          >
            <button class="agcfg-expand-btn">
              <ChevronRightIcon
                v-if="!expanded['route-' + r.action]"
                class="w-3 h-3"
              />
              <ChevronDownIcon
                v-else
                class="w-3 h-3"
              />
            </button>
            <div class="agcfg-item-name">
              {{ r.action }}
            </div>
            <div class="agcfg-item-workflow">
              {{ r.workflow }}
            </div>
          </div>
          <div class="agcfg-item-desc">
            {{ r.description }}
          </div>
          <div
            v-if="routeTemplateMap[r.action]"
            class="agcfg-templates"
          >
            <span class="agcfg-templates-label">{{ t('settings.agent.templatesLabel') }}:</span>
            <span
              v-for="tid in routeTemplateMap[r.action]"
              :key="tid"
              class="badge badge-scene"
            >{{ tid }}</span>
          </div>
          <pre
            v-if="expanded['route-' + r.action]"
            class="agcfg-json"
          >{{ itemJson(r) }}</pre>
        </div>
      </div>

      <!-- Skills -->
      <div
        v-show="activeSubTab === 'skills'"
        class="agcfg-list"
      >
        <div
          v-for="s in filteredSkills"
          :key="s.name"
          class="agcfg-item"
        >
          <div
            class="agcfg-item-header"
            @click="toggleExpand('skill-' + s.name)"
          >
            <button class="agcfg-expand-btn">
              <ChevronRightIcon
                v-if="!expanded['skill-' + s.name]"
                class="w-3 h-3"
              />
              <ChevronDownIcon
                v-else
                class="w-3 h-3"
              />
            </button>
            <div class="agcfg-item-name">
              {{ s.name }}
            </div>
            <div class="agcfg-item-meta">
              {{ t('settings.agent.stepCount', { count: s.steps }) }}
            </div>
          </div>
          <div class="agcfg-item-desc">
            {{ s.description }}
          </div>
          <pre
            v-if="expanded['skill-' + s.name]"
            class="agcfg-json"
          >{{ itemJson(s) }}</pre>
        </div>
      </div>

      <!-- Tools (Agent batch) -->
      <div
        v-show="activeSubTab === 'tools'"
        class="agcfg-list"
      >
        <div
          v-for="tool in filteredTools"
          :key="tool.name"
          class="agcfg-item"
        >
          <div
            class="agcfg-item-header"
            @click="toggleExpand('tool-' + tool.name)"
          >
            <button class="agcfg-expand-btn">
              <ChevronRightIcon
                v-if="!expanded['tool-' + tool.name]"
                class="w-3 h-3"
              />
              <ChevronDownIcon
                v-else
                class="w-3 h-3"
              />
            </button>
            <div class="agcfg-item-name">
              {{ tool.name }}
            </div>
            <div class="agcfg-item-meta">
              {{ tool.category }} | {{ tool.llm_visible ? t('settings.agent.llmVisible') : t('settings.agent.internal') }}
            </div>
          </div>
          <div class="agcfg-item-desc">
            {{ tool.description }}
          </div>
          <pre
            v-if="expanded['tool-' + tool.name]"
            class="agcfg-json"
          >{{ itemJson(tool) }}</pre>
        </div>
      </div>

      <!-- Web AI Chat tools -->
      <div
        v-show="activeSubTab === 'chat'"
        class="agcfg-list"
      >
        <div class="agcfg-chat-hint">
          {{ t('settings.agent.chatHint') }}
        </div>
        <div
          v-for="tool in filteredChatTools"
          :key="tool.name"
          class="agcfg-item"
        >
          <div
            class="agcfg-item-header"
            @click="toggleExpand('chat-' + tool.name)"
          >
            <button class="agcfg-expand-btn">
              <ChevronRightIcon
                v-if="!expanded['chat-' + tool.name]"
                class="w-3 h-3"
              />
              <ChevronDownIcon
                v-else
                class="w-3 h-3"
              />
            </button>
            <div class="agcfg-item-name">
              {{ tool.name }}
            </div>
          </div>
          <div class="agcfg-item-desc">
            {{ tool.description }}
          </div>
          <div
            v-if="tool.parameters"
            class="agcfg-chat-params"
          >
            <span class="agcfg-chat-params-label">{{ t('settings.agent.paramLabel') }}:</span>
            <span
              v-for="(desc, pname) in tool.parameters"
              :key="pname"
              class="badge badge-param"
            >{{ pname }}</span>
          </div>
          <pre
            v-if="expanded['chat-' + tool.name]"
            class="agcfg-json"
          >{{ itemJson(tool) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agcfg-container { padding: 0.75rem; }
.agcfg-intro { font-size: 0.7rem; color: var(--text-secondary); line-height: 1.5; padding: 0.4rem 0.5rem; margin-bottom: 0.5rem; background: var(--bg-secondary); border-radius: 6px; }
.agcfg-tabs { display: flex; gap: 0.25rem; margin-bottom: 0.5rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; align-items: center; }
.agcfg-tab { font-size: 0.7rem; padding: 0.2rem 0.6rem; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-secondary); color: var(--text-muted); cursor: pointer; }
.agcfg-tab.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.agcfg-tab-chat { border-color: #a78bfa; color: #a78bfa; }
.agcfg-tab-chat.active { background: #7c3aed; border-color: #7c3aed; color: #fff; }
.agcfg-tab-sep { color: var(--border); font-size: 0.8rem; margin: 0 0.15rem; user-select: none; }
.agcfg-loading, .agcfg-error { text-align: center; padding: 1rem; font-size: 0.75rem; color: var(--text-muted); }
.agcfg-error { color: var(--danger, #ef4444); }
.agcfg-search { margin-bottom: 0.5rem; }
.agcfg-search-input { width: 100%; font-size: 0.75rem; padding: 0.3rem 0.5rem; }
.agcfg-list { display: flex; flex-direction: column; gap: 0.5rem; max-height: 55vh; overflow-y: auto; }
.agcfg-item { background: var(--bg-primary); border: 1px solid var(--border); border-radius: 6px; padding: 0.4rem 0.75rem; }
.agcfg-item-header { display: flex; align-items: center; gap: 0.5rem; cursor: pointer; user-select: none; }
.agcfg-expand-btn { background: none; border: none; color: var(--text-muted); cursor: pointer; padding: 0; display: flex; align-items: center; flex-shrink: 0; }
.agcfg-item-name { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); font-family: var(--font-mono); }
.agcfg-item-workflow { font-size: 0.65rem; color: var(--accent); margin-left: auto; white-space: nowrap; }
.agcfg-item-meta { font-size: 0.65rem; color: var(--text-muted); white-space: nowrap; }
.agcfg-item-desc { font-size: 0.7rem; color: var(--text-secondary); margin-top: 0.25rem; }
.agcfg-templates { display: flex; align-items: center; gap: 0.25rem; margin-top: 0.25rem; flex-wrap: wrap; }
.agcfg-templates-label { font-size: 0.65rem; color: var(--text-muted); }
.agcfg-templates .badge-scene { font-size: 0.6rem; padding: 0.1rem 0.35rem; background: #e0f2fe; color: #0369a1; border: 1px solid #7dd3fc; border-radius: 3px; }
.agcfg-json { font-size: 0.6rem; font-family: var(--font-mono); color: var(--text-secondary); background: var(--bg-secondary); padding: 0.4rem; border-radius: 4px; margin-top: 0.25rem; overflow-x: auto; white-space: pre; }
.agcfg-chat-hint { font-size: 0.7rem; color: var(--text-secondary); padding: 0.3rem 0.5rem; background: var(--bg-secondary); border-radius: 4px; }
.agcfg-chat-params { display: flex; align-items: center; gap: 0.25rem; margin-top: 0.25rem; flex-wrap: wrap; }
.agcfg-chat-params-label { font-size: 0.65rem; color: var(--text-muted); }
.badge-param { font-size: 0.55rem; padding: 0.1rem 0.3rem; border-radius: 3px; font-family: var(--font-mono); background: var(--bg-secondary); color: var(--text-secondary); border: 1px solid var(--border); }
</style>
