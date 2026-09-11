<script setup lang="ts">
/**
 * MCP 服务管理（S4）：architect 资产地图对外暴露面。
 * - 服务通道：stdio（python3 -m topoone_app_architect.mcp）+ HTTP（/mcp streamable）
 * - 工具目录：map.overview / map.component / map.assets / map.rules / map.graph（MD 输出）
 * - 调用日志：arch_mcp_calls（MCP server 工具调用 + 外部 agent 经 KB :3460 转发）
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ServerIcon, CommandLineIcon, GlobeAltIcon, WrenchIcon, ClipboardDocumentIcon,
} from '@heroicons/vue/24/outline'
import PageHeader from '@/components/PageHeader.vue'
import { useArchMcpStore } from '@/stores/mcp-store'
import { backendUp } from '@/services/backend'
import { copyText } from '@/utils/clipboard'

const { t } = useI18n()
const mcp = useArchMcpStore()
mcp.load()

const httpUp = ref(false)
const origin = window.location.origin
const httpUrl = computed(() => `${origin.replace(/:\d+$/, ':3470')}/mcp/mcp`)
const stdioCmd = 'python3 -m topoone_app_architect.mcp'
const claudeCmd = computed(() => `claude mcp add topo-architect -- ${stdioCmd}`)
const copied = ref('')

const TOOLS = [
  { name: 'map.overview', desc: () => t('mcp.tools.overview') },
  { name: 'map.component', desc: () => t('mcp.tools.component') },
  { name: 'map.assets', desc: () => t('mcp.tools.assets') },
  { name: 'map.rules', desc: () => t('mcp.tools.rules') },
  { name: 'map.graph', desc: () => t('mcp.tools.graph') },
]

onMounted(async () => {
  try {
    httpUp.value = await backendUp() // 探活（同进程架构：architect 可达即 MCP HTTP 可达）
  } catch { httpUp.value = false }
})

async function copy(text: string, key: string) {
  if (await copyText(text)) {
    copied.value = key
    setTimeout(() => { copied.value = '' }, 1500)
  }
}
</script>

<template>
  <div class="p-5 space-y-4">
    <PageHeader :title="t('mcp.title')" :desc="t('mcp.desc')" />

    <!-- 服务通道 -->
    <div class="grid md:grid-cols-2 gap-3">
      <div class="panel p-3 space-y-2">
        <div class="flex items-center gap-2 text-sm">
          <CommandLineIcon class="w-4 h-4 text-ctp-green" />
          <span class="font-semibold">{{ t('mcp.stdio.title') }}</span>
        </div>
        <div class="text-[11px] text-ctp-overlay0">{{ t('mcp.stdio.desc') }}</div>
        <div class="flex items-center gap-1.5">
          <code class="flex-1 text-[11px] font-mono bg-ctp-surface0 rounded px-2 py-1.5 truncate">{{ stdioCmd }}</code>
          <button class="btn btn-xs" @click="copy(stdioCmd, 'stdio')">
            <ClipboardDocumentIcon class="w-3 h-3" />{{ copied === 'stdio' ? '✓' : t('mcp.copy') }}
          </button>
        </div>
        <div class="text-[10px] text-ctp-overlay0">{{ t('mcp.stdio.claude') }}</div>
        <div class="flex items-center gap-1.5">
          <code class="flex-1 text-[10px] font-mono bg-ctp-surface0 rounded px-2 py-1 truncate">{{ claudeCmd }}</code>
          <button class="btn btn-xs" @click="copy(claudeCmd, 'claude')">
            <ClipboardDocumentIcon class="w-3 h-3" />{{ copied === 'claude' ? '✓' : t('mcp.copy') }}
          </button>
        </div>
      </div>

      <div class="panel p-3 space-y-2">
        <div class="flex items-center gap-2 text-sm">
          <GlobeAltIcon class="w-4 h-4 text-ctp-sky" />
          <span class="font-semibold">{{ t('mcp.http.title') }}</span>
          <span
            class="chip"
            :class="httpUp ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-red/15 text-ctp-red'"
          >{{ httpUp ? '● up' : '○ down' }}</span>
        </div>
        <div class="text-[11px] text-ctp-overlay0">{{ t('mcp.http.desc') }}</div>
        <div class="flex items-center gap-1.5">
          <code class="flex-1 text-[11px] font-mono bg-ctp-surface0 rounded px-2 py-1.5 truncate">{{ httpUrl }}</code>
          <button class="btn btn-xs" @click="copy(httpUrl, 'http')">
            <ClipboardDocumentIcon class="w-3 h-3" />{{ copied === 'http' ? '✓' : t('mcp.copy') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 工具目录 -->
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <WrenchIcon class="w-4 h-4 text-ctp-peach" />{{ t('mcp.tools.title') }}
        </span>
        <span class="text-[11px] text-ctp-overlay1">{{ TOOLS.length }}</span>
      </div>
      <div class="divide-y divide-ctp-surface0">
        <div v-for="tool in TOOLS" :key="tool.name" class="flex items-start gap-2 px-4 py-2 text-xs">
          <code class="font-mono text-ctp-sapphire shrink-0">{{ tool.name }}</code>
          <span class="text-ctp-subtext1">{{ tool.desc() }}</span>
        </div>
      </div>
    </div>

    <!-- 调用日志 -->
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <ServerIcon class="w-4 h-4 text-ctp-mauve" />{{ t('mcp.calls.title') }}
        </span>
        <span class="text-[11px] text-ctp-overlay1">{{ mcp.calls.length }}</span>
      </div>
      <div class="divide-y divide-ctp-surface0">
        <div v-if="!mcp.calls.length" class="px-4 py-3 text-xs text-ctp-overlay1">
          {{ t('mcp.calls.empty') }}
        </div>
        <div
          v-for="c in mcp.calls"
          :key="c.id"
          class="flex items-center gap-2 px-4 py-2 text-xs"
        >
          <span
            class="chip shrink-0"
            :class="c.status === 'ok' ? 'bg-ctp-green/15 text-ctp-green' : c.status === 'pending' ? 'bg-ctp-yellow/15 text-ctp-yellow' : 'bg-ctp-red/15 text-ctp-red'"
          >{{ c.status }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0 shrink-0">{{ (c as any).input?.source || 'mcp' }}</span>
          <code class="font-mono text-ctp-sapphire shrink-0">{{ c.tool }}</code>
          <span class="text-ctp-overlay0 truncate flex-1">{{ (c as any).input?.detail || '' }}</span>
          <span class="text-[10px] text-ctp-overlay0 shrink-0">{{ new Date((c as any).time).toLocaleTimeString() }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
