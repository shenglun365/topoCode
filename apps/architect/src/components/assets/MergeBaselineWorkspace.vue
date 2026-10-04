<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowsRightLeftIcon, ClockIcon, CodeBracketIcon,
  CircleStackIcon, InboxIcon, CheckBadgeIcon, PaperAirplaneIcon,
} from '@heroicons/vue/24/outline'
import { useArchMergeBaselineStore } from '@/stores/merge-baseline-store'
import { useArchProjectStore } from '@/stores/project-store'
import { semanticAssetService, type GraphPartition } from '@/services/semantic-asset-service'

const { t } = useI18n()
const merge = useArchMergeBaselineStore()
const project = useArchProjectStore()

onMounted(() => {
  project.load()
  merge.load()
})

const statusCls = (s: string) =>
  s === 'A' ? 'bg-ctp-green/15 text-ctp-green'
    : s === 'D' ? 'bg-ctp-red/15 text-ctp-red'
      : s === 'R' ? 'bg-ctp-lavender/15 text-ctp-lavender'
        : 'bg-ctp-peach/15 text-ctp-peach'

const baselineCommit = computed(() => project.status?.head.commit ?? '')
const syncStatus = computed(() => merge.sync.status)

function fmtDate(ts: number): string {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

function fmtTs(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts)
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// ── D3 分区: >5000 文件项目先提案后勾选执行(部分执行可重入) ──
const partitions = ref<GraphPartition[]>([])
const partHead = ref('')
const selected = ref<Set<number>>(new Set())
const partBusy = ref(false)
const partMsg = ref('')

async function buildPlan() {
  partBusy.value = true
  partMsg.value = ''
  try {
    const r = await semanticAssetService.collectGraphPlan()
    if (!r) { partMsg.value = t('mergeBaseline.planFailed'); return }
    partitions.value = r.partitions || []
    partHead.value = r.head || ''
    selected.value = new Set((r.partitions || []).map((p) => p.idx))
    if (!r.needsConfirmation) partMsg.value = t('mergeBaseline.planSingle')
  } catch (e: any) {
    partMsg.value = e?.message || String(e)
  } finally {
    partBusy.value = false
  }
}

function toggleSel(idx: number) {
  const s = new Set(selected.value)
  if (s.has(idx)) s.delete(idx)
  else s.add(idx)
  selected.value = s
}

async function confirmPartitions() {
  partBusy.value = true
  partMsg.value = t('mergeBaseline.partStarting')
  try {
    const r = await semanticAssetService.collectGraphConfirm([...selected.value], partHead.value)
    partMsg.value = r?.message || (r?.started ? '' : t('mergeBaseline.planFailed'))
    if (r?.started) void merge.load()
  } catch (e: any) {
    partMsg.value = e?.message || String(e)
  } finally {
    partBusy.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <!-- D3 分区: 大项目(>5000 文件)自动拆分提案 → 勾选部分执行 -->
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <CircleStackIcon class="w-4 h-4 text-ctp-teal" />{{ t('mergeBaseline.partitions') }}
        </span>
        <button class="btn btn-ghost !py-1 !px-3 !text-xs" :disabled="partBusy" @click="buildPlan">
          {{ t('mergeBaseline.buildPlan') }}
        </button>
      </div>
      <div v-if="partitions.length" class="p-4 space-y-2">
        <div
          v-for="p in partitions"
          :key="p.idx"
          class="flex items-center gap-3 rounded-lg border px-3 py-2 text-xs cursor-pointer"
          :class="selected.has(p.idx) ? 'border-ctp-teal/50 bg-ctp-teal/5' : 'border-ctp-surface0'"
          @click="toggleSel(p.idx)"
        >
          <input type="checkbox" :checked="selected.has(p.idx)" class="accent-ctp-teal pointer-events-none" />
          <span class="font-mono text-ctp-overlay1">#{{ p.idx }}</span>
          <span class="text-ctp-text">{{ p.files.length }} {{ t('mergeBaseline.files') }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ p.langs.join('/') || '—' }}</span>
          <span class="text-ctp-overlay0">≈{{ p.estSymbols }} {{ t('mergeBaseline.symbols') }}</span>
          <span class="text-[10px] text-ctp-overlay0">{{ p.reason }}</span>
        </div>
        <div class="flex items-center gap-2 pt-1">
          <button class="btn btn-primary !py-1 !px-3 !text-xs" :disabled="partBusy || !selected.size" @click="confirmPartitions">
            {{ t('mergeBaseline.confirmRun') }} ({{ selected.size }})
          </button>
          <span v-if="partMsg" class="text-[11px] text-ctp-overlay1">{{ partMsg }}</span>
        </div>
      </div>
      <p v-else class="p-4 text-[11px] text-ctp-subtext0">
        {{ t('mergeBaseline.partitionHint', { cap: 5000 }) }}
        <span v-if="partMsg" class="block text-ctp-peach mt-1">{{ partMsg }}</span>
      </p>
    </div>

    <!-- Git 提交历史: 基线为起始点到当前最新 commit 的历次变更 -->
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <ClockIcon class="w-4 h-4 text-ctp-sapphire" />{{ t('mergeBaseline.commitHistory') }}
        </span>
        <span class="chip bg-ctp-surface0 text-ctp-subtext0">
          {{ t('mergeBaseline.fromBaseline') }} {{ merge.commits.length ? merge.commits[merge.commits.length - 1].short : '—' }}
          → {{ baselineCommit.slice(0, 7) }}
        </span>
      </div>

      <div class="p-4 space-y-2">
        <p class="text-[11px] text-ctp-subtext0 -mt-1">
          {{ t('mergeBaseline.commitHint') }}
        </p>
        <div
          v-for="c in merge.commits"
          :key="c.hash"
          class="relative flex gap-3 pl-4"
        >
          <span class="absolute left-1 top-1 bottom-0 w-px bg-ctp-surface0" />
          <span
            class="absolute left-[5px] top-4 w-[5px] h-[5px] rounded-full shrink-0"
            :class="c.hash === merge.commits[merge.commits.length - 1]?.hash ? 'bg-ctp-sapphire' : 'bg-ctp-overlay0'"
          />
          <div class="flex-1 min-w-0 pb-2.5">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-mono text-[11px] text-ctp-mauve">{{ c.short }}</span>
              <span
                v-if="c.hash === merge.commits[merge.commits.length - 1]?.hash"
                class="chip bg-ctp-sapphire/15 text-ctp-sapphire"
              >{{ t('mergeBaseline.startPoint') }}</span>
              <span class="text-sm text-ctp-text truncate">{{ c.message }}</span>
            </div>
            <div class="text-[11px] text-ctp-overlay1 mt-0.5">
              {{ c.author }} · {{ fmtTs(c.date) }}
            </div>
            <div
              v-if="c.files.length"
              class="flex flex-wrap gap-1 mt-1.5"
            >
              <span
                v-for="f in c.files"
                :key="f.path"
                class="chip"
                :class="statusCls(f.status)"
                :title="`+${f.add} −${f.del}`"
              >
                {{ f.status }} {{ f.path }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 未提交变更: 提示用户提交，不强制 -->
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <InboxIcon class="w-4 h-4 text-ctp-peach" />{{ t('mergeBaseline.uncommitted') }}
        </span>
        <span
          class="chip"
          :class="merge.hasUncommitted ? 'bg-ctp-peach/15 text-ctp-peach' : 'bg-ctp-green/15 text-ctp-green'"
        >{{ merge.hasUncommitted ? t('mergeBaseline.dirty') : t('mergeBaseline.clean') }}</span>
      </div>

      <div class="p-4">
        <template v-if="merge.hasUncommitted">
          <p class="text-[11px] text-ctp-subtext0 -mt-1 mb-2">
            {{ t('mergeBaseline.uncommittedHint') }}
          </p>
          <div class="flex flex-wrap gap-1.5 mb-3">
            <span
              v-for="f in merge.uncommitted"
              :key="f.path"
              class="chip"
              :class="statusCls(f.status)"
              :title="`+${f.add} −${f.del}`"
            >
              {{ f.status }} {{ f.path }}
            </span>
          </div>
          <div class="flex items-center gap-2">
            <button
              class="btn btn-sm btn-primary"
              @click="merge.commitUncommitted()"
            >
              <CodeBracketIcon class="w-4 h-4" />{{ t('mergeBaseline.commitDo') }}
            </button>
            <span class="text-[11px] text-ctp-overlay1">{{ t('mergeBaseline.notForced') }}</span>
          </div>
        </template>
        <template v-else>
          <div class="flex items-center gap-2 text-xs text-ctp-green">
            <CheckBadgeIcon class="w-4 h-4" />{{ t('mergeBaseline.cleanOk') }}
          </div>
        </template>
      </div>
    </div>

    <!-- 向知识库发送基线变更请求: 基于 git 同步，不直接传递变更数据 -->
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <ArrowsRightLeftIcon class="w-4 h-4 text-ctp-mauve" />{{ t('mergeBaseline.kbSync') }}
        </span>
        <span
          class="chip"
          :class="{
            'bg-ctp-surface0 text-ctp-subtext0': syncStatus === 'idle',
            'bg-ctp-yellow/15 text-ctp-yellow': syncStatus === 'syncing',
            'bg-ctp-green/15 text-ctp-green': syncStatus === 'done',
            'bg-ctp-red/15 text-ctp-red': syncStatus === 'error',
          }"
        >{{ t(`mergeBaseline.sync.${syncStatus}`) }}</span>
      </div>

      <div class="p-4 space-y-3">
        <p class="text-[11px] text-ctp-subtext0 -mt-1">
          {{ t('mergeBaseline.kbSyncHint') }}
        </p>

        <template v-if="merge.sync.request">
          <div class="flex flex-wrap gap-1.5">
            <span class="chip bg-ctp-surface0 text-ctp-sapphire">{{ t('mergeBaseline.branch') }} {{ merge.sync.request.branch }}</span>
            <span class="chip bg-ctp-surface0 text-ctp-teal">{{ t('mergeBaseline.tag') }} {{ merge.sync.request.tag }}</span>
            <span class="chip bg-ctp-surface0 text-ctp-mauve font-mono">{{ t('mergeBaseline.commit') }} {{ merge.sync.request.commit.slice(0, 7) }}</span>
          </div>
          <div
            v-if="merge.done"
            class="text-[11px] text-ctp-green"
          >
            ✓ {{ merge.sync.message }} · {{ fmtDate(merge.sync.requestedAt) }}
          </div>
          <div
            v-if="merge.failed"
            class="text-[11px] text-ctp-red"
          >
            ✗ {{ merge.sync.message }}
          </div>
          <div
            v-else-if="merge.syncing && merge.sync.message"
            class="text-[11px] text-ctp-subtext0"
          >
            {{ merge.sync.message }}
          </div>
        </template>

        <button
          class="btn btn-sm"
          :class="merge.done ? 'btn-ghost' : 'btn-mauve'"
          :disabled="merge.syncing"
          @click="merge.sendBaselineSync()"
        >
          <PaperAirplaneIcon class="w-4 h-4" />
          {{ merge.syncing ? `${t('common.loading')}…` : merge.done ? `${t('mergeBaseline.sendSync')} ↻` : t('mergeBaseline.sendSync') }}
        </button>
      </div>
    </div>
  </div>
</template>