<script setup lang="ts">
/**
 * 基线管理 · 宏观概览（P3 瘦身裁决）——impact 视图从「单帧三 tab 图」
 * 改为宏观统计 + 组件汇总图 + 版本历史 + 深链。
 * 图谱细节(组件/文件/符号粒度 + 演化时间轴)统一在资产地图 → 图谱 → 演化时间轴。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextIcon, CubeIcon, ArrowPathIcon, BoltIcon,
} from '@heroicons/vue/24/outline'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import { projectService } from '@/services/project-service'
import { componentsToMermaid } from '@/utils/diagram-gen'
import type { EvolutionFrames } from '@/types'

const { t } = useI18n()

const loading = ref(false)
const error = ref('')
const compFrames = ref<EvolutionFrames | null>(null)
const fileFrames = ref<EvolutionFrames | null>(null)
const versions = ref<Array<{ id: string; label: string; head: string; createdAt: string }>>([])

const headFrame = computed(() => compFrames.value?.frames?.at(-1) ?? null)
const lastFileFrame = computed(() => fileFrames.value?.frames?.at(-1) ?? null)
const stats = computed(() => {
  // 统一 JSON(存在性投影): 末帧 nodes=存活组件; modified=该帧变更组件
  const head = headFrame.value
  const changedComps = head?.modified?.length ?? 0
  const files = lastFileFrame.value?.nodes ?? []
  const nameOf = (k: string) => compFrames.value?.canonical.nodes.find((n) => n.key === k)?.label ?? k
  const scan = (keys: string[]) => {
    let add = 0, del = 0
    for (const k of keys) {
      add += Number((nameOf(k).match(/\+(\d+)/) ?? [])[1]) || 0
      del += Number((nameOf(k).match(/-(\d+)/) ?? [])[1]) || 0
    }
    return { add, del }
  }
  const { add, del } = scan(files)
  return {
    files: files.length,
    components: head?.nodes?.length ?? 0,
    changedComponents: changedComps,
    commits: (compFrames.value?.frames?.length ?? 1) - 1,
    add,
    del,
  }
})

/** 组件汇总图(宏观档)：当前基线组件依赖全景(业务名, canonical 全量结构)。 */
const overviewMermaid = computed(() => {
  const d = compFrames.value
  if (!d?.canonical?.nodes?.length) return ''
  const nameOf = (k: string) => d.canonical.nodes.find((n) => n.key === k)?.label ?? k
  // Mermaid 节点 ID 不允许引号/特殊字符——sanitize，显示文本才用引号。
  const mid = (k: string) => k.replace(/[^A-Za-z0-9_-]/g, '_')
  const lines = ['flowchart LR']
  const last = d.frames.at(-1)
  const alive = new Set(last?.nodes ?? [])
  for (const n of d.canonical.nodes) {
    lines.push(`  ${mid(n.key)}[${JSON.stringify(nameOf(n.key))}]`)
    if (!alive.has(n.key)) lines.push(`  class ${mid(n.key)} gray`)
  }
  const seen = new Set<string>()
  for (const e of d.canonical.edges) {
    if (seen.has(e.key ?? `${e.from}->${e.to}`)) continue
    seen.add(e.key ?? `${e.from}->${e.to}`)
    lines.push(`  ${mid(e.from)} --> ${mid(e.to)}`)
  }
  return lines.join('\n')
})

/** PlantUML 组件图版依赖关系（与 overviewMermaid 同源数据，供 DiagramCard 语言切换）。 */
const overviewPlantuml = computed(() => {
  const d = compFrames.value
  if (!d?.canonical?.nodes?.length) return ''
  const nameOf = (k: string) => d.canonical.nodes.find((n) => n.key === k)?.label ?? k
  const mid = (k: string) => 'n' + k.replace(/[^A-Za-z0-9_]/g, '_')
  const last = d.frames.at(-1)
  const alive = new Set(last?.nodes ?? [])
  const lines = ['@startuml', 'skinparam shadowing false']
  for (const n of d.canonical.nodes) {
    const color = alive.has(n.key) ? '' : ' #8b8b9e'
    lines.push(`component "${nameOf(n.key).replace(/"/g, "'")}" as ${mid(n.key)}${color}`)
  }
  const seen = new Set<string>()
  for (const e of d.canonical.edges) {
    if (seen.has(e.key ?? `${e.from}->${e.to}`)) continue
    seen.add(e.key ?? `${e.from}->${e.to}`)
    lines.push(`${mid(e.from)} --> ${mid(e.to)}`)
  }
  lines.push('@enduml')
  return lines.join('\n')
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [c, f, v] = await Promise.all([
      projectService.evolutionFrames('baseline', 'HEAD', 'component'),
      projectService.evolutionFrames('baseline', 'HEAD', 'file'),
      projectService.versions(),
    ])
    compFrames.value = c
    fileFrames.value = f
    versions.value = v ?? []
  } catch (e: any) {
    error.value = e?.message || t('nav.tree.loadFailed')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <!-- 统计卡 -->
    <div class="grid grid-cols-3 md:grid-cols-6 gap-2">
      <div v-for="s in ([
        { icon: DocumentTextIcon, label: t('archChange.ovFiles'), value: stats.files },
        { icon: CubeIcon, label: t('archChange.ovComponents'), value: stats.components },
        { icon: CubeIcon, label: t('archChange.ovChangedComps'), value: stats.changedComponents },
        { icon: BoltIcon, label: t('archChange.ovCommits'), value: stats.commits },
        { icon: ArrowPathIcon, label: t('archChange.ovAdded'), value: `+${stats.add}` },
        { icon: ArrowPathIcon, label: t('archChange.ovDeleted'), value: `-${stats.del}` },
      ] as const)" :key="s.label" class="panel p-3">
        <component :is="s.icon" class="w-4 h-4 text-ctp-overlay0 mb-1" />
        <div class="text-lg font-semibold text-ctp-text">{{ s.value }}</div>
        <div class="text-[10px] text-ctp-overlay1">{{ s.label }}</div>
      </div>
    </div>

    <div v-if="error" class="panel p-4 text-xs text-ctp-peach">{{ error }}</div>
    <div v-if="loading" class="panel p-4 text-xs text-ctp-overlay0 flex items-center gap-2">
      <ArrowPathIcon class="w-4 h-4 animate-spin" />{{ t('assetMgmt.diff.cmpRunning') }}
    </div>

    <!-- 组件汇总图(宏观档) -->
    <section v-if="overviewMermaid || overviewPlantuml" class="panel p-4">
      <div class="flex items-center gap-2 mb-3">
        <CubeIcon class="w-4 h-4 text-ctp-mauve" />
        <span class="text-sm font-medium text-ctp-text">{{ t('archChange.ovCompGraph') }}</span>
        <span class="flex-1" />
      </div>
      <DiagramCard :title="t('archChange.mapTitle.dependency')" :diagrams="{ mermaid: overviewMermaid, plantuml: overviewPlantuml }" />
    </section>

    <!-- 版本历史 -->
    <section class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2 text-xs text-ctp-subtext0">
          <ArrowPathIcon class="w-4 h-4 text-ctp-sapphire" />{{ t('archChange.ovVersions') }}
        </span>
        <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ versions.length }}</span>
      </div>
      <div class="max-h-64 overflow-y-auto divide-y divide-ctp-surface0/50">
        <div v-for="v in versions" :key="v.id" class="px-4 py-2 text-xs flex items-center gap-3">
          <span class="text-ctp-text font-medium">{{ v.label }}</span>
          <span class="font-mono text-ctp-overlay0">{{ v.head.slice(0, 7) }}</span>
          <span class="flex-1" />
          <span class="text-ctp-overlay1">{{ v.createdAt || '' }}</span>
        </div>
        <p v-if="!versions.length" class="px-4 py-3 text-xs text-ctp-subtext0">
          {{ t('archChange.ovNoVersions') }}
        </p>
      </div>
    </section>
  </div>
</template>
