<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowsRightLeftIcon, ClockIcon, CodeBracketIcon,
  InboxIcon, CheckBadgeIcon, PaperAirplaneIcon,
} from '@heroicons/vue/24/outline'
import { useArchMergeBaselineStore } from '@/stores/merge-baseline-store'
import { useArchProjectStore } from '@/stores/project-store'

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
</script>

<template>
  <div class="space-y-4">
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
        </template>

        <button
          class="btn btn-sm"
          :class="merge.done ? 'btn-ghost' : 'btn-mauve'"
          :disabled="merge.syncing || merge.done"
          @click="merge.sendBaselineSync()"
        >
          <PaperAirplaneIcon class="w-4 h-4" />
          {{ merge.syncing ? `${t('common.loading')}…` : merge.done ? `${t('common.done')} ✓` : t('mergeBaseline.sendSync') }}
        </button>
      </div>
    </div>
  </div>
</template>