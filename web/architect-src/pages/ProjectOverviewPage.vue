<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderIcon, DocumentTextIcon, CubeIcon,
  CodeBracketIcon, CheckCircleIcon, XCircleIcon,
} from '@heroicons/vue/24/outline'
import { projectService } from '@/services/project-service'
import type { ProjectOverview } from '@/types'

const { t } = useI18n()

const loading = ref(false)
const overview = ref<ProjectOverview | null>(null)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    overview.value = await projectService.overview()
  } catch {
    overview.value = null
    error.value = t('overviewHome.loadFailed')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const diffSummary = computed(() => [
  { label: t('overviewHome.added'), value: overview.value?.diff.added ?? 0, cls: 'text-ctp-green' },
  { label: t('overviewHome.modified'), value: overview.value?.diff.modified ?? 0, cls: 'text-ctp-blue' },
  { label: t('overviewHome.deleted'), value: overview.value?.diff.deleted ?? 0, cls: 'text-ctp-red' },
])

function statusLabel(s: string): string {
  if (s === 'A') return t('overviewHome.stAdded')
  if (s === 'D') return t('overviewHome.stDeleted')
  if (s === 'R') return t('overviewHome.stRenamed')
  return t('overviewHome.stModified')
}
function statusCls(s: string): string {
  return s === 'A' ? 'text-ctp-green' : s === 'D' ? 'text-ctp-red' : 'text-ctp-blue'
}
</script>

<template>
  <div class="p-6 max-w-6xl mx-auto space-y-5">
    <p v-if="error" class="text-xs text-ctp-red">{{ error }}</p>
    <p v-if="loading" class="text-xs text-ctp-subtext0">{{ t('app.loading') }}</p>

    <template v-if="overview">
      <!-- ① 基本信息 -->
      <section class="panel p-5">
        <div class="flex items-center gap-2 mb-4">
          <FolderIcon class="w-4 h-4 text-ctp-blue" />
          <span class="text-sm font-medium text-ctp-text">{{ t('overviewHome.basicTitle') }}</span>
        </div>
        <dl class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3 text-sm">
          <div class="flex items-start gap-2">
            <dt class="text-ctp-overlay1 shrink-0 w-24">{{ t('overviewHome.workDir') }}</dt>
            <dd class="text-ctp-text font-mono text-xs break-all flex items-center gap-1">
              {{ overview.workDir }}
            </dd>
          </div>
          <div class="flex items-start gap-2">
            <dt class="text-ctp-overlay1 shrink-0 w-24">{{ t('overviewHome.remoteUrl') }}</dt>
            <dd class="text-ctp-text font-mono text-xs break-all">
              {{ overview.remoteUrl || t('overviewHome.notConfigured') }}
            </dd>
          </div>
          <div class="flex items-start gap-2">
            <dt class="text-ctp-overlay1 shrink-0 w-24">{{ t('overviewHome.branch') }}</dt>
            <dd class="text-ctp-text flex items-center gap-1.5">
              <CodeBracketIcon class="w-3.5 h-3.5 text-ctp-green" />
              <span class="font-mono text-xs">{{ overview.head.branch || overview.branch || 'main' }}</span>
              <span v-if="overview.head.ahead > 0" class="chip bg-ctp-green/15 text-ctp-green">+{{ overview.head.ahead }}</span>
              <span v-if="overview.head.dirty" class="chip bg-ctp-peach/15 text-ctp-peach">{{ t('overviewHome.dirty') }}</span>
            </dd>
          </div>
          <div class="flex items-start gap-2">
            <dt class="text-ctp-overlay1 shrink-0 w-24">{{ t('overviewHome.headCommit') }}</dt>
            <dd class="text-ctp-text font-mono text-xs">{{ overview.head.commit?.slice(0, 8) || t('common.na') }}</dd>
          </div>
        </dl>
      </section>

      <!-- ② 知识库关联 -->
      <section class="panel p-5">
        <div class="flex items-center gap-2 mb-4">
          <DocumentTextIcon class="w-4 h-4 text-ctp-peach" />
          <span class="text-sm font-medium text-ctp-text">{{ t('overviewHome.kbLink') }}</span>
        </div>
        <div v-if="overview.kb.linked" class="text-sm text-ctp-text">
          <span class="inline-flex items-center gap-1.5 text-ctp-green text-xs">
            <CheckCircleIcon class="w-4 h-4" /> {{ t('overviewHome.kbLinked') }}
          </span>
          <div class="mt-2 space-y-1">
            <div v-if="overview.kb.kbProjectId" class="text-xs text-ctp-subtext1">
              <span class="text-ctp-overlay1">{{ t('overviewHome.kbProject') }}:</span>
              <span class="font-mono">{{ overview.kb.kbProjectId }}</span>
            </div>
            <div v-if="overview.kb.kbSourceDir" class="text-xs text-ctp-subtext1">
              <span class="text-ctp-overlay1">{{ t('overviewHome.kbSource') }}:</span>
              <span class="font-mono break-all">{{ overview.kb.kbSourceDir }}</span>
            </div>
          </div>
        </div>
        <div v-else class="text-sm text-ctp-subtext0 flex items-center gap-1.5">
          <span class="inline-flex items-center gap-1.5 text-ctp-red text-xs">
            <XCircleIcon class="w-4 h-4" /> {{ t('overviewHome.kbNotLinked') }}
          </span>
        </div>
      </section>

      <!-- ③ 基线信息 -->
      <section class="panel p-4">
        <div class="flex items-center gap-2 mb-3">
          <DocumentTextIcon class="w-4 h-4 text-ctp-sapphire" />
          <span class="text-sm font-medium text-ctp-text">{{ t('overviewHome.baseline') }}</span>
        </div>
        <p v-if="overview.baseline.exists" class="text-xs text-ctp-text font-mono">
          {{ overview.baseline.commit?.slice(0, 8) }}
          <span v-if="overview.baseline.id" class="text-ctp-overlay1"> ({{ overview.baseline.id }})</span>
        </p>
        <p v-else class="text-xs text-ctp-subtext0">{{ t('overviewHome.noBaseline') }}</p>
      </section>

      <!-- ④ 组件变更情况 -->
      <section class="panel p-4">
        <div class="flex items-center gap-2 mb-3">
          <CubeIcon class="w-4 h-4 text-ctp-mauve" />
          <span class="text-sm font-medium text-ctp-text">{{ t('overviewHome.componentChanges') }}</span>
        </div>
        <div v-if="overview.kb.linked && overview.diff.byComponent.length" class="grid grid-cols-1 md:grid-cols-2 gap-2">
          <div
            v-for="c in overview.diff.byComponent"
            :key="c.name"
            class="border border-ctp-surface0 rounded-lg px-3 py-2"
          >
            <div class="flex items-center justify-between mb-1">
              <span class="text-sm text-ctp-text font-medium">{{ c.name }}</span>
              <span class="text-[11px] text-ctp-overlay1">{{ c.files.length }} {{ t('overviewHome.filesUnit') }}</span>
            </div>
            <div class="flex gap-2 text-[11px]">
              <span class="text-ctp-green">{{ t('overviewHome.added') }} {{ c.added }}</span>
              <span class="text-ctp-blue">{{ t('overviewHome.modified') }} {{ c.modified }}</span>
              <span class="text-ctp-red">{{ t('overviewHome.deleted') }} {{ c.deleted }}</span>
            </div>
          </div>
        </div>
        <p v-if="!overview.kb.linked" class="text-xs text-ctp-subtext0">{{ t('overviewHome.noComponentNeedKb') }}</p>
        <p v-else-if="!overview.diff.byComponent.length" class="text-xs text-ctp-subtext0">{{ t('overviewHome.noComponentChange') }}</p>
      </section>

      <!-- ⑤ 代码变更情况（对比基线） -->
      <section class="panel p-4">
        <div class="flex items-center gap-2 mb-3">
          <CodeBracketIcon class="w-4 h-4 text-ctp-green" />
          <span class="text-sm font-medium text-ctp-text">{{ t('overviewHome.codeChanges') }}</span>
        </div>

        <template v-if="overview.kb.linked">
        <div class="flex gap-4 mb-3 text-sm">
          <span class="text-ctp-subtext1 flex items-center gap-1">
            <DocumentTextIcon class="w-4 h-4 text-ctp-overlay0" />{{ overview.diff.filesChanged }} {{ t('overviewHome.filesChanged') }}
          </span>
          <template v-for="s in diffSummary" :key="s.label">
            <span class="flex items-center gap-1">
              <span :class="s.cls">{{ s.value }}</span>
              <span class="text-ctp-overlay1">{{ s.label }}</span>
            </span>
          </template>
        </div>

        <div v-if="overview.diff.files.length" class="max-h-72 overflow-y-auto border border-ctp-surface0 rounded-lg">
          <table class="w-full text-xs">
            <thead class="sticky top-0 bg-ctp-mantle text-ctp-overlay1">
              <tr>
                <th class="text-left px-3 py-2 w-16">{{ t('overviewHome.status') }}</th>
                <th class="text-left px-3 py-2">{{ t('overviewHome.file') }}</th>
                <th class="text-right px-3 py-2 w-40">{{ t('overviewHome.lines') }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ctp-surface0/60">
              <tr v-for="f in overview.diff.files" :key="f.path" class="hover:bg-ctp-surface0/40">
                <td class="px-3 py-1.5 font-mono" :class="statusCls(f.status)">{{ statusLabel(f.status) }}</td>
                <td class="px-3 py-1.5 font-mono text-ctp-text truncate" :title="f.path">{{ f.path }}</td>
                <td class="px-3 py-1.5 text-right font-mono text-ctp-overlay1">
                  <span class="text-ctp-green">+{{ f.additions }}</span>
                  <span class="text-ctp-red">-{{ f.deletions }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="text-xs text-ctp-subtext0">{{ t('overviewHome.noCodeChange') }}</p>
      </template>
      <p v-else class="text-xs text-ctp-subtext0">{{ t('overviewHome.noCodeNeedKb') }}</p>
      </section>
    </template>
  </div>
</template>