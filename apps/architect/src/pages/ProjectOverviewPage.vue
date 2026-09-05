<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderIcon, DocumentTextIcon, CubeIcon,
  CodeBracketIcon, CheckCircleIcon, XCircleIcon, MagnifyingGlassIcon, ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import { projectService } from '@/services/project-service'
import type { KbMatchResult, ProjectOverview, ProjectOverviewComponent } from '@/types'
import KbLinkDialog from '@/components/project/KbLinkDialog.vue'
import { useArchProjectStore } from '@/stores/project-store'

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

const showLinkDialog = ref(false)
const linkMatch = ref<KbMatchResult | null>(null)
const matching = ref(false)
const unlinking = ref(false)

async function openLinkDialog() {
  matching.value = true
  try {
    linkMatch.value = await projectService.matchKbProjects()
  } catch {
    linkMatch.value = null
  } finally {
    matching.value = false
    showLinkDialog.value = true
  }
}

function closeLinkDialog() {
  showLinkDialog.value = false
  load()
}

async function askUnlink() {
  if (!window.confirm(t('overviewHome.unlinkConfirm'))) return
  unlinking.value = true
  try {
    await useArchProjectStore().unlinkKb()
    await load()
  } catch {
    error.value = t('overviewHome.loadFailed')
  } finally {
    unlinking.value = false
  }
}

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

// ---- 组件变更：组件树父子层级渲染(逐层可开可闭，含未归属分组) + 分组展开到变更文件清单 ----
interface CompTreeNode { c: ProjectOverviewComponent; children: CompTreeNode[] }

const compTree = computed<CompTreeNode[]>(() => {
  const list = overview.value?.diff.byComponent ?? []
  const map = new Map<string, CompTreeNode>(list.map((c) => [c.id, { c, children: [] }]))
  const roots: CompTreeNode[] = []
  for (const node of map.values()) {
    const parent = node.c.parentId ? map.get(node.c.parentId) : undefined
    if (parent && parent !== node) parent.children.push(node)
    else roots.push(node)
  }
  return roots
})

const expandedComps = ref<Set<string>>(new Set())
const filesOpenComps = ref<Set<string>>(new Set())

watch(compTree, (tree) => {
  expandedComps.value = new Set(tree.map((n) => n.c.id))   // 默认展开顶层，子层收起
  filesOpenComps.value = new Set()
})

/** 可见节点(DFS)：收起的组件其子树不渲染。 */
const visibleComps = computed(() => {
  const out: { c: ProjectOverviewComponent; children: CompTreeNode[] }[] = []
  const walk = (nodes: CompTreeNode[]) => {
    for (const n of nodes) {
      out.push(n)
      if (expandedComps.value.has(n.c.id)) walk(n.children)
    }
  }
  walk(compTree.value)
  return out
})

function toggleComp(id: string) {
  const next = new Set(expandedComps.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedComps.value = next
}

function toggleCompFiles(id: string) {
  const next = new Set(filesOpenComps.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  filesOpenComps.value = next
}

const allExpanded = computed(() => compTree.value.length > 0 &&
  compTree.value.every((r) => expandedComps.value.has(r.c.id)))

function toggleAllComps() {
  expandedComps.value = allExpanded.value
    ? new Set()
    : new Set(compTree.value.map((n) => n.c.id))
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
          <div class="flex items-center gap-2">
            <span class="inline-flex items-center gap-1.5 text-ctp-green text-xs">
              <CheckCircleIcon class="w-4 h-4" /> {{ t('overviewHome.kbLinked') }}
            </span>
            <button
              class="btn btn-blue !px-2.5 !py-1 text-xs shrink-0"
              :disabled="matching"
              @click="openLinkDialog"
            >
              <MagnifyingGlassIcon class="w-3.5 h-3.5" />
              {{ matching ? t('app.loading') : t('overviewHome.switchLink') }}
            </button>
            <button
              class="btn btn-ghost !px-2.5 !py-1 text-xs shrink-0"
              :disabled="unlinking"
              @click="askUnlink"
            >
              {{ unlinking ? t('app.loading') : t('overviewHome.unlink') }}
            </button>
          </div>
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
          <!-- 基线信息(并入知识库关联组，不单列)：基线 commit + 分支 + 仓库 -->
          <div class="mt-3 pt-2.5 border-t border-ctp-surface0/70 flex items-center gap-2 text-xs flex-wrap">
            <span class="text-ctp-overlay1 shrink-0">{{ t('overviewHome.baseline') }}</span>
            <template v-if="overview.baseline.exists">
              <span class="font-mono text-ctp-text">{{ overview.baseline.commit?.slice(0, 8) }}</span>
              <span v-if="overview.baseline.id" class="font-mono text-ctp-overlay1">({{ overview.baseline.id }})</span>
            </template>
            <span v-else class="text-ctp-subtext0">{{ t('overviewHome.noBaseline') }}</span>
            <span class="text-ctp-surface1 shrink-0">|</span>
            <span class="text-ctp-overlay1 shrink-0">{{ t('overviewHome.branch') }}</span>
            <span class="font-mono text-ctp-text">{{ overview.head.branch || overview.branch || 'main' }}</span>
            <span class="text-ctp-surface1 shrink-0">|</span>
            <span class="text-ctp-overlay1 shrink-0">{{ t('overviewHome.repo') }}</span>
            <span
              class="chip shrink-0"
              :class="overview.repoKind === 'remote' ? 'bg-ctp-sky/15 text-ctp-sky' : 'bg-ctp-surface0 text-ctp-subtext1'"
              :title="overview.repoKind === 'remote' ? t('overviewHome.repoRemoteHint') : t('overviewHome.repoLocalHint')"
            >{{ overview.repoKind === 'remote' ? t('overviewHome.repoRemote') : t('overviewHome.repoLocal') }}</span>
            <span
              class="font-mono text-ctp-text truncate max-w-[40ch]"
              :title="overview.repoKind === 'remote' ? overview.remoteUrl : overview.workDir"
            >{{ overview.repoKind === 'remote' ? overview.remoteUrl : overview.workDir }}</span>
          </div>
        </div>
        <div v-else class="text-sm text-ctp-subtext0 flex items-center gap-1.5 flex-wrap">
          <span class="inline-flex items-center gap-1.5 text-ctp-red text-xs">
            <XCircleIcon class="w-4 h-4" /> {{ t('overviewHome.kbNotLinked') }}
          </span>
          <button
            class="btn btn-blue !px-2.5 !py-1 text-xs ml-2 shrink-0"
            :disabled="matching"
            @click="openLinkDialog"
          >
            <MagnifyingGlassIcon class="w-3.5 h-3.5" />
            {{ matching ? t('app.loading') : t('overviewHome.findLink') }}
          </button>
          <span class="text-xs text-ctp-subtext0">{{ t('overviewHome.noBaseline') }}</span>
        </div>
      </section>

      <KbLinkDialog
        v-if="showLinkDialog"
        :match-result="linkMatch"
        @close="closeLinkDialog"
      />

      <!-- ③ 组件变更情况（组件树父子层级 · 逐层开合 · 含未归属分组 · 可展开到变更文件） -->
      <section class="panel p-4">
        <div class="flex items-center gap-2 mb-3">
          <CubeIcon class="w-4 h-4 text-ctp-mauve" />
          <span class="text-sm font-medium text-ctp-text">{{ t('overviewHome.componentChanges') }}</span>
          <span class="flex-1" />
          <button
            v-if="overview.kb.linked && compTree.length"
            class="btn btn-ghost !px-1.5 !py-0.5 !text-[10px]"
            @click="toggleAllComps"
          >{{ allExpanded ? t('overviewHome.collapseAll') : t('overviewHome.expandAll') }}</button>
        </div>
        <div v-if="overview.kb.linked && compTree.length" class="space-y-1">
          <template v-for="node in visibleComps" :key="node.c.id">
            <div
              class="flex items-center gap-1.5 border border-ctp-surface0 rounded-lg px-3 py-2"
              :style="{ marginLeft: `${node.c.level * 20}px` }"
            >
              <button
                v-if="node.children.length"
                class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                :title="expandedComps.has(node.c.id) ? t('overviewHome.collapse') : t('overviewHome.expand')"
                @click.stop="toggleComp(node.c.id)"
              >
                <ChevronRightIcon class="w-3.5 h-3.5 transition-transform" :class="expandedComps.has(node.c.id) ? 'rotate-90' : ''" />
              </button>
              <span v-else class="w-[18px] shrink-0" />
              <span
                class="truncate text-sm"
                :class="node.c.level > 0 ? 'text-ctp-subtext1' : 'text-ctp-text font-medium'"
                :title="node.c.id === '__unowned__' ? t('overviewHome.unownedHint') : `${node.c.name || t('overviewHome.unowned')} (${node.c.id})`"
              >{{ node.c.name || t('overviewHome.unowned') }}</span>
              <span class="flex-1" />
              <button
                class="flex items-center gap-1 text-[11px] text-ctp-overlay1 hover:text-ctp-text shrink-0"
                :title="t('overviewHome.filesToggle')"
                @click.stop="toggleCompFiles(node.c.id)"
              >
                <DocumentTextIcon class="w-3.5 h-3.5" />
                {{ node.c.files.length }} {{ t('overviewHome.filesUnit') }}
                <ChevronRightIcon class="w-3 h-3 transition-transform" :class="filesOpenComps.has(node.c.id) ? 'rotate-90' : ''" />
              </button>
              <span class="text-[11px] text-ctp-green shrink-0">{{ t('overviewHome.added') }} {{ node.c.totalAdded ?? node.c.added }}</span>
              <span class="text-[11px] text-ctp-blue shrink-0">{{ t('overviewHome.modified') }} {{ node.c.totalModified ?? node.c.modified }}</span>
              <span class="text-[11px] text-ctp-red shrink-0">{{ t('overviewHome.deleted') }} {{ node.c.totalDeleted ?? node.c.deleted }}</span>
            </div>
            <!-- 变更文件清单(分组内联展开；父组件为含子孙的并集) -->
            <div
              v-if="filesOpenComps.has(node.c.id) && node.c.files.length"
              class="border border-ctp-surface0/60 rounded-lg bg-ctp-mantle/40 overflow-hidden max-h-64 overflow-y-auto"
              :style="{ marginLeft: `${(node.c.level + 1) * 20}px` }"
            >
              <div
                v-for="f in node.c.files"
                :key="f"
                class="px-3 py-1 font-mono text-[10px] text-ctp-subtext0 truncate border-b border-ctp-surface0/40 last:border-b-0"
                :title="f"
              >{{ f }}</div>
            </div>
          </template>
        </div>
        <p v-if="!overview.kb.linked" class="text-xs text-ctp-subtext0">{{ t('overviewHome.noComponentNeedKb') }}</p>
        <p v-else-if="!compTree.length" class="text-xs text-ctp-subtext0">{{ t('overviewHome.noComponentChange') }}</p>
      </section>

      <!-- ④ 代码变更情况（对比基线） -->
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