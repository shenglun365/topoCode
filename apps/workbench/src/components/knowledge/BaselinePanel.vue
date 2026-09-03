<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, TrashIcon, CheckIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { ipc } from '@topo/web-core/services/ipc'
import { useComponentId } from '@topo/web-core/composables/useComponentId'
import { useProjectStore } from '@/stores/project'
import type { ProjectVersion, VersionPreview, VersionSyncResult } from '@topo/web-core/types/ipc'

const { showId, componentId } = useComponentId('KB-010')
const { t } = useI18n()
const projectStore = useProjectStore()

const projectId = computed(() => projectStore.selectedProjectId)

const pending = ref<any[]>([])
const versions = ref<ProjectVersion[]>([])
const loading = ref(false)
const busy = ref(false)
const confirmPreview = ref<Record<string, VersionPreview>>({})
const syncResult = ref<VersionSyncResult | null>(null)
const cleanupResult = ref<Record<string, number> | null>(null)
const errMsg = ref('')

async function load() {
  if (!projectId.value) return
  loading.value = true
  errMsg.value = ''
  try {
    const [p, v] = await Promise.all([
      ipc.knowledge.pendingUpdates(projectId.value).catch(() => [] as any[]),
      ipc.version.list(projectId.value).catch(() => [] as ProjectVersion[]),
    ])
    pending.value = Array.isArray(p) ? p : []
    versions.value = Array.isArray(v) ? v : []
  } catch (e: any) {
    errMsg.value = e?.message || t('knowledge.baseline.err')
  } finally {
    loading.value = false
  }
}

async function confirmRequest(req: any) {
  busy.value = true
  errMsg.value = ''
  try {
    const pv = await ipc.knowledge.updateConfirm(req.requestId || req.id, { method: 'pull' })
    confirmPreview.value[req.requestId || req.id] = pv as VersionPreview
  } catch (e: any) {
    errMsg.value = e?.message || t('knowledge.baseline.err')
  } finally {
    busy.value = false
  }
}

async function cancelRequest(req: any) {
  busy.value = true
  try {
    await ipc.knowledge.updateCancel(req.requestId || req.id)
    await load()
  } catch (e: any) {
    errMsg.value = e?.message || t('knowledge.baseline.err')
  } finally {
    busy.value = false
  }
}

async function runSync() {
  if (!projectId.value) return
  busy.value = true
  errMsg.value = ''
  syncResult.value = null
  const rid = pending.value[0]?.requestId || pending.value[0]?.id || undefined
  try {
    const res = await ipc.version.sync(projectId.value, {
      stages: { ast: true, graph: true, presummary: false, community: true, llm: false },
      requestId: rid,
    })
    syncResult.value = res as VersionSyncResult
    await load()
  } catch (e: any) {
    errMsg.value = e?.message || t('knowledge.baseline.err')
  } finally {
    busy.value = false
  }
}

async function runCleanup(keep: number) {
  if (!projectId.value) return
  if (!window.confirm(t('knowledge.baseline.cleanupConfirm'))) return
  busy.value = true
  errMsg.value = ''
  cleanupResult.value = null
  try {
    const res = await ipc.version.cleanup(projectId.value, { keepVersions: keep })
    cleanupResult.value = (res as any).deleted || {}
  } catch (e: any) {
    errMsg.value = e?.message || t('knowledge.baseline.err')
  } finally {
    busy.value = false
  }
}

function headShort(h?: string) {
  return (h || '').slice(0, 8)
}

watch(projectId, () => { syncResult.value = null; cleanupResult.value = null; load() })
onMounted(load)
</script>

<template>
  <div class="card" style="padding: calc(12px * var(--ui-scale, 1)); display: flex; flex-direction: column; gap: calc(10px * var(--ui-scale, 1));">
    <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <div style="display:flex; align-items:center; gap: calc(8px * var(--ui-scale, 1));">
      <ArrowPathIcon class="w-4 h-4 text-accent" />
      <span style="font-size: calc(13px * var(--ui-scale, 1)); font-weight: 600;">{{ t('knowledge.baseline.title') }}</span>
      <button class="btn btn-ghost !py-1 !px-2 !text-[11px]" :disabled="loading || busy" @click="load">
        {{ t('knowledge.baseline.syncing') }}
      </button>
    </div>
    <p style="margin:0; font-size: calc(10px * var(--ui-scale, 1)); color: var(--text-muted); line-height: 1.5;">
      {{ t('knowledge.baseline.desc') }}
    </p>

    <div v-if="!projectId" class="badge badge-yellow" style="font-size: calc(10px * var(--ui-scale, 1));">
      {{ t('knowledge.baseline.noProject') }}
    </div>

    <template v-else>
      <!-- 待确认请求 -->
      <div>
        <div style="font-size: calc(11px * var(--ui-scale, 1)); font-weight: 600; margin-bottom: calc(4px * var(--ui-scale, 1));">
          {{ t('knowledge.baseline.pending') }} ({{ pending.length }})
        </div>
        <div v-if="!pending.length" style="font-size: calc(10px * var(--ui-scale, 1)); color: var(--text-muted);">
          {{ t('knowledge.baseline.noPending') }}
        </div>
        <div v-for="req in pending" :key="req.requestId || req.id"
             class="card" style="padding: calc(8px * var(--ui-scale, 1)); margin-bottom: calc(6px * var(--ui-scale, 1)); font-size: calc(10px * var(--ui-scale, 1));">
          <div style="display:flex; align-items:center; gap: calc(8px * var(--ui-scale, 1)); flex-wrap: wrap;">
            <span class="badge badge-blue">{{ req.branch || 'main' }}</span>
            <span class="font-mono" style="color: var(--text-muted);">{{ headShort(req.head) }}</span>
            <span v-if="req.note" style="color: var(--text-muted);">{{ req.note }}</span>
            <div style="margin-left:auto; display:flex; gap: calc(6px * var(--ui-scale, 1));">
              <button class="btn btn-ghost !py-0.5 !px-2 !text-[10px]" :disabled="busy" @click="confirmRequest(req)">
                <CheckIcon class="w-3 h-3 inline" /> {{ t('knowledge.baseline.confirm') }}
              </button>
              <button class="btn btn-ghost !py-0.5 !px-2 !text-[10px]" :disabled="busy" @click="cancelRequest(req)">
                <XMarkIcon class="w-3 h-3 inline" /> {{ t('knowledge.baseline.cancel') }}
              </button>
            </div>
          </div>
          <div v-if="confirmPreview[req.requestId || req.id]?.delta" style="margin-top: calc(6px * var(--ui-scale, 1)); color: var(--text-muted);">
            {{ t('knowledge.baseline.added') }} {{ confirmPreview[req.requestId || req.id].delta!.addedCount }} ·
            {{ t('knowledge.baseline.modified') }} {{ confirmPreview[req.requestId || req.id].delta!.modifiedCount }} ·
            {{ t('knowledge.baseline.deleted') }} {{ confirmPreview[req.requestId || req.id].delta!.deletedCount }}
            <span v-if="confirmPreview[req.requestId || req.id].changeType" class="badge badge-yellow" style="margin-left: calc(6px * var(--ui-scale, 1));">
              {{ confirmPreview[req.requestId || req.id].changeType }}
            </span>
          </div>
        </div>
      </div>

      <!-- 操作 -->
      <div style="display:flex; gap: calc(8px * var(--ui-scale, 1)); flex-wrap: wrap;">
        <button class="btn btn-primary !py-1 !px-3 !text-xs" :disabled="busy" @click="runSync">
          {{ t('knowledge.baseline.syncNow') }}
        </button>
        <button class="btn btn-ghost !py-1 !px-3 !text-xs" :disabled="busy" @click="runCleanup(1)">
          <TrashIcon class="w-3 h-3 inline" /> {{ t('knowledge.baseline.cleanup') }} ({{ t('knowledge.baseline.keepOne') }})
        </button>
        <button class="btn btn-ghost !py-1 !px-3 !text-xs" :disabled="busy" @click="runCleanup(0)">
          {{ t('knowledge.baseline.keepAll') }}
        </button>
      </div>

      <!-- 同步结果 -->
      <div v-if="syncResult" class="card" style="padding: calc(8px * var(--ui-scale, 1)); font-size: calc(10px * var(--ui-scale, 1)); color: var(--text-muted);">
        <span style="font-weight:600;">{{ t('knowledge.baseline.result') }}:</span>
        <template v-if="syncResult.changed">
          {{ syncResult.version?.id }} ({{ headShort(syncResult.version?.head) }}) ·
          {{ t('knowledge.baseline.added') }} {{ syncResult.delta?.added.length || 0 }} ·
          {{ t('knowledge.baseline.modified') }} {{ syncResult.delta?.modified.length || 0 }} ·
          {{ t('knowledge.baseline.deleted') }} {{ syncResult.delta?.deleted.length || 0 }}
          · archived {{ syncResult.archivedRows || 0 }}
        </template>
        <template v-else>{{ (syncResult as any).message || 'no changes' }}</template>
      </div>

      <!-- 清除结果 -->
      <div v-if="cleanupResult" class="card" style="padding: calc(8px * var(--ui-scale, 1)); font-size: calc(10px * var(--ui-scale, 1)); color: var(--text-muted);">
        <span style="font-weight:600;">{{ t('knowledge.baseline.cleanup') }}:</span>
        <span v-for="(n, tbl) in cleanupResult" :key="tbl" style="margin-left: calc(6px * var(--ui-scale, 1));">
          {{ tbl }}:{{ n }}
        </span>
      </div>

      <!-- 基线版本 -->
      <div>
        <div style="font-size: calc(11px * var(--ui-scale, 1)); font-weight: 600; margin-bottom: calc(4px * var(--ui-scale, 1));">
          {{ t('knowledge.baseline.versions') }} ({{ versions.length }})
        </div>
        <div v-if="!versions.length" style="font-size: calc(10px * var(--ui-scale, 1)); color: var(--text-muted);">
          {{ t('knowledge.baseline.noVersions') }}
        </div>
        <div v-for="v in versions" :key="v.id"
             style="display:flex; align-items:center; gap: calc(8px * var(--ui-scale, 1)); padding: calc(4px * var(--ui-scale, 1)) 0; font-size: calc(10px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border-subtle);">
          <span class="badge badge-blue">{{ v.branch || 'main' }}</span>
          <span class="font-mono" style="color: var(--text-muted);">{{ headShort(v.head) }}</span>
          <span v-if="v.label" style="color: var(--text-muted);">{{ v.label }}</span>
          <span style="margin-left:auto; color: var(--text-muted);">
            {{ t('knowledge.baseline.added') }} {{ v.addedCount || 0 }} ·
            {{ t('knowledge.baseline.modified') }} {{ v.modifiedCount || 0 }} ·
            {{ t('knowledge.baseline.deleted') }} {{ v.deletedCount || 0 }}
          </span>
        </div>
      </div>
    </template>

    <div v-if="errMsg" class="badge badge-red" style="font-size: calc(10px * var(--ui-scale, 1));">
      {{ errMsg }}
    </div>
  </div>
</template>
