<script setup lang="ts">
/**
 * 会话删除确认对话框(2610 裁决): 主会话删除前置预览 + 二次确认。
 *
 * - 详细清单: 关联需求(完成情况, 仅展示不强制校验) + 执行器子会话(运行状态)
 *   + 需求跟踪条目数;
 * - 执行中(执行器会话未完成) → 阻断删除(deletable=false, 仅可关闭);
 * - 二次确认: 删除按钮两段式(首击进入待确认态, 5s 内再击执行)。
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ExclamationTriangleIcon, TrashIcon, XMarkIcon, CheckCircleIcon,
} from '@heroicons/vue/24/outline'
import {
  sessionService, type ConversationMeta, type SessionDeletePreview,
} from '@/services/session-service'

const props = defineProps<{ session: ConversationMeta | null }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'deleted', id: string): void
}>()

const { t } = useI18n()
const preview = ref<SessionDeletePreview | null>(null)
const loading = ref(false)
const error = ref('')
const armed = ref(false)
const deleting = ref(false)
let armTimer: number | undefined

async function load() {
  if (!props.session) return
  loading.value = true
  error.value = ''
  preview.value = null
  armed.value = false
  try {
    preview.value = await sessionService.deletePreview(props.session.id)
  } catch (e: any) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}
// immediate: v-if 挂载时 prop 已就位——watcher 仅响应"变化", 不补 immediate
// 则 load() 永不执行(正文三分支全落空=空窗; 删除钮 v-if preview 恒隐)
watch(() => props.session, () => { void load() }, { immediate: true })

function resetArm() {
  armed.value = false
  if (armTimer) window.clearTimeout(armTimer)
}
function close() {
  resetArm()
  emit('close')
}
async function onConfirmDelete() {
  if (!props.session || !preview.value?.deletable || deleting.value) return
  if (!armed.value) {
    armed.value = true
    armTimer = window.setTimeout(() => { armed.value = false }, 5000)
    return
  }
  resetArm()
  deleting.value = true
  try {
    await sessionService.remove(props.session.id)
    emit('deleted', props.session.id)
  } catch (e: any) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    deleting.value = false
  }
}

function reqStatusLabel(s: string): string {
  const key = `session.deleteDialog.reqStatus.${s}`
  const label = t(key)
  return label === key ? s : label
}
function execStatusLabel(s: string): string {
  const key = `session.deleteDialog.execStatus.${s}`
  const label = t(key)
  return label === key ? s : label
}
const isExecuting = (s: string) => !!s
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 p-4 backdrop-blur-sm"
    @click.self="close"
  >
    <div class="panel flex max-h-[80vh] w-full max-w-lg flex-col">
      <div class="panel-header shrink-0">
        <span class="flex items-center gap-1.5 text-ctp-red">
          <ExclamationTriangleIcon class="h-4 w-4" />
          {{ t('session.deleteDialog.title', { title: session?.title || '' }) }}
        </span>
        <button
          class="btn btn-xs btn-ghost"
          @click="close"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>

      <div class="min-h-0 flex-1 space-y-3 overflow-auto p-3 text-xs">
        <p
          v-if="loading"
          class="py-6 text-center text-ctp-overlay0"
        >
          {{ t('session.deleteDialog.loading') }}
        </p>
        <p
          v-else-if="error"
          class="rounded-lg bg-ctp-red/10 p-2 text-ctp-red break-all"
        >
          {{ error }}
        </p>

        <template v-else-if="preview">
          <!-- 阻断: 执行器会话执行中(须先停止/等待完成) -->
          <div
            v-if="!preview.deletable"
            class="rounded-lg border border-ctp-red/40 bg-ctp-red/10 p-2.5"
          >
            <p class="font-medium text-ctp-red">
              {{ t('session.deleteDialog.blockedTitle') }}
            </p>
            <p class="mt-1 text-ctp-subtext0">
              {{ t('session.deleteDialog.blockedHint') }}
            </p>
            <ul class="mt-1.5 space-y-1">
              <li
                v-for="b in preview.blockers"
                :key="b.id"
                class="flex items-center gap-1.5 rounded bg-ctp-surface0/60 px-2 py-1"
              >
                <span class="chip shrink-0 animate-pulse bg-ctp-peach/20 text-ctp-peach">
                  {{ execStatusLabel(b.status) }}
                </span>
                <span
                  class="min-w-0 flex-1 truncate"
                  :title="b.title"
                >{{ b.title }}</span>
                <span
                  v-if="b.executorId"
                  class="shrink-0 font-mono text-[10px] text-ctp-overlay0"
                >{{ b.executorId }}</span>
                <span
                  v-if="b.self"
                  class="chip shrink-0 bg-ctp-surface1 text-ctp-overlay1"
                >
                  {{ t('session.deleteDialog.selfSession') }}
                </span>
              </li>
            </ul>
          </div>

          <!-- 汇总: 将删除范围 -->
          <p class="text-ctp-subtext1">
            {{ t('session.deleteDialog.summary', {
              subs: preview.subSessions.length,
              reqs: preview.requirements.filter((r) => r.willDelete).length,
              tracks: preview.trackingItemCount,
            }) }}
          </p>

          <!-- 需求完成情况(仅展示, 不强制校验) -->
          <section>
            <p class="mb-1 text-[10px] font-medium uppercase tracking-wider text-ctp-overlay1">
              {{ t('session.deleteDialog.reqsTitle') }}
            </p>
            <ul
              v-if="preview.requirements.length"
              class="space-y-1"
            >
              <li
                v-for="r in preview.requirements"
                :key="r.id"
                class="flex items-center gap-1.5 rounded border border-ctp-surface1 px-2 py-1"
              >
                <span
                  class="chip shrink-0"
                  :class="r.status === 'done' ? 'bg-ctp-green/15 text-ctp-green' : r.status === 'cancelled' ? 'bg-ctp-surface0 text-ctp-overlay0' : 'bg-ctp-blue/15 text-ctp-blue'"
                >
                  {{ reqStatusLabel(r.status) }}
                </span>
                <CheckCircleIcon
                  v-if="r.doneMark"
                  class="h-3 w-3 shrink-0 text-ctp-green"
                />
                <span
                  class="min-w-0 flex-1 truncate"
                  :title="r.title"
                >{{ r.title }}</span>
                <span
                  v-if="r.shared"
                  class="chip shrink-0 bg-ctp-yellow/15 text-ctp-yellow"
                  :title="t('session.deleteDialog.sharedHint')"
                >{{ t('session.deleteDialog.sharedKeep') }}</span>
                <span
                  v-else
                  class="chip shrink-0 bg-ctp-red/15 text-ctp-red"
                >
                  {{ t('session.deleteDialog.willDelete') }}
                </span>
              </li>
            </ul>
            <p
              v-else
              class="text-ctp-overlay0"
            >
              {{ t('session.deleteDialog.noReqs') }}
            </p>
          </section>

          <!-- 执行器子会话运行状态 -->
          <section>
            <p class="mb-1 text-[10px] font-medium uppercase tracking-wider text-ctp-overlay1">
              {{ t('session.deleteDialog.subsTitle') }}
            </p>
            <ul
              v-if="preview.subSessions.length"
              class="space-y-1"
            >
              <li
                v-for="s in preview.subSessions"
                :key="s.id"
                class="flex items-center gap-1.5 rounded border border-ctp-surface1 px-2 py-1"
              >
                <span
                  class="chip shrink-0"
                  :class="isExecuting(s.execution) ? 'animate-pulse bg-ctp-peach/20 text-ctp-peach' : 'bg-ctp-surface0 text-ctp-overlay0'"
                >{{ isExecuting(s.execution) ? execStatusLabel(s.execution) : t('session.deleteDialog.execIdle') }}</span>
                <span
                  class="min-w-0 flex-1 truncate"
                  :title="s.title"
                >{{ s.title }}</span>
                <span
                  v-if="s.executorId"
                  class="shrink-0 font-mono text-[10px] text-ctp-mauve"
                >{{ s.executorId }}</span>
                <span class="shrink-0 text-[10px] text-ctp-overlay0">{{ s.msgCount }} {{ t('session.msgUnit') }}</span>
              </li>
            </ul>
            <p
              v-else
              class="text-ctp-overlay0"
            >
              {{ t('session.deleteDialog.noSubs') }}
            </p>
          </section>

          <p class="text-[10px] text-ctp-overlay0">
            {{ t('session.deleteDialog.irreversible') }}
          </p>
        </template>
      </div>

      <div class="flex shrink-0 items-center justify-end gap-2 border-t border-ctp-surface0 px-3 py-2">
        <button
          class="btn btn-sm btn-ghost"
          @click="close"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          v-if="preview?.deletable"
          class="btn btn-sm"
          :class="armed ? 'btn-red animate-pulse' : 'btn-primary'"
          :disabled="deleting || loading"
          @click="onConfirmDelete"
        >
          <TrashIcon class="h-3.5 w-3.5" />
          {{ deleting ? '…' : armed ? t('session.deleteDialog.confirmAgain') : t('session.deleteDialog.confirm') }}
        </button>
      </div>
    </div>
  </div>
</template>
