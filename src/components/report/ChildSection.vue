<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useReportStore } from '@/stores/report'

const { t } = useI18n()
const reportStore = useReportStore()

const props = defineProps<{
  taskId: string
  parentLevel: string
  parentCommId: string
  edgeType: string
  projectId?: string
}>()

const emit = defineEmits(['openChildAnalysis', 'viewCommunityMD'])

const childLevel = computed(() => `L${parseInt(props.parentLevel[1]) + 1}`)

const loading = ref(true)
const error = ref<string | null>(null)

const stateKey = computed(() => reportStore.buildChildStateKey(props.parentLevel, props.parentCommId, props.edgeType))
const communities = computed(() => {
  const state = reportStore.tasks[props.taskId]?.analysisStates[stateKey.value]
  return state?.communities || []
})

onMounted(async () => {
  loading.value = true
  error.value = null
  try {
    await reportStore.loadChildCommunities(props.taskId, props.parentLevel, props.parentCommId, props.edgeType)
  } catch (e: any) {
    error.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
})

function fmtCommId(id: string): string {
  return id.replace(/^comm-[^-]+-/, '')
}

function openAnalysis() {
  emit('openChildAnalysis', {
    taskId: props.taskId,
    parentLevel: props.parentLevel,
    parentCommId: props.parentCommId,
    edgeType: props.edgeType,
    projectId: props.projectId,
  })
}

function viewMD(c: any) {
  console.log(`[ChildSection] viewMD clicked id=${c.communityId} status=${c.status} name=${c.name}`)
  if (c.status === 'completed' && c.name) {
    console.log(`[ChildSection] viewMD emitting viewCommunityMD`, { communityId: c.communityId, level: c.level, edgeType: c.edgeType, parentLevel: childLevel.value, parentCommId: c.communityId, name: c.name })
    emit('viewCommunityMD', {
      communityId: c.communityId,
      level: c.level,
      edgeType: c.edgeType,
      parentLevel: childLevel.value,
      parentCommId: c.communityId,
      name: c.name,
      summary: c.summary || '',
      mermaid: c.mermaid,
      plantuml: c.plantuml,
    })
  } else {
    console.warn(`[ChildSection] viewMD SKIP status=${c.status} name=${c.name}`)
  }
}
</script>

<template>
  <div class="child-section">
    <div class="child-section-header">
      <span class="child-section-title">{{ childLevel }} {{ t('report.pipeline.childAnalysis') }}</span>
      <button class="btn btn-primary btn-xs" @click="openAnalysis">
        {{ t('report.pipeline.enterChildAnalysis', { level: childLevel }) }}
      </button>
    </div>

    <div v-if="loading" class="child-section-loading">{{ t('common.loading') }}...</div>
    <div v-else-if="error" class="child-section-error">{{ error }}</div>
    <div v-else-if="communities.length === 0" class="child-section-empty">
      {{ t('report.pipeline.noChildCommunities') }}
    </div>
    <div v-else class="child-section-list">
      <div
        v-for="c in communities"
        :key="c.id"
        :class="['child-comm-item', { clickable: c.status === 'completed' && c.name }]"
        @click="c.status === 'completed' && c.name && viewMD(c)"
      >
        <span class="child-comm-id">{{ fmtCommId(c.communityId) }}</span>
        <span
          v-if="c.status === 'completed' && c.name"
          class="child-comm-name clickable"
        >{{ c.name }}</span>
        <span v-else class="child-comm-name pending">{{ t('common.pending') }}</span>
        <span :class="['child-comm-status', `status-${c.status}`]">
          {{ c.status === 'completed' ? t('common.completed') : c.status === 'error' ? t('common.error') : t('common.pending') }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.child-section {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-secondary);
  margin-top: 12px;
  font-size: 12px;
}
.child-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-tertiary);
  border-radius: 8px 8px 0 0;
}
.child-section-title {
  font-weight: 600;
  color: var(--text-primary);
}
.child-section-loading,
.child-section-empty,
.child-section-error {
  padding: 12px;
  text-align: center;
  color: var(--text-muted);
  font-size: 11px;
}
.child-section-error {
  color: var(--error);
}
.child-section-list {
  padding: 4px 0;
}
.child-comm-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  font-size: 10px;
}
.child-comm-item:hover {
  background: var(--bg-tertiary);
}
.child-comm-item.clickable {
  cursor: pointer;
}
.child-comm-id {
  font-family: var(--font-mono);
  color: var(--text-primary);
  font-size: 9px;
  min-width: 60px;
}
.child-comm-name {
  color: var(--text-secondary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.child-comm-name.clickable {
  cursor: pointer;
  color: var(--accent);
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 2px;
}
.child-comm-name.clickable:hover {
  opacity: 0.8;
}
.child-comm-name.pending {
  color: var(--text-muted);
}
.child-comm-status {
  font-size: 8px;
  padding: 1px 5px;
  border-radius: 4px;
  white-space: nowrap;
}
.status-completed {
  background: color-mix(in srgb, var(--success) 15%, transparent);
  color: var(--success);
}
.status-error {
  background: color-mix(in srgb, var(--error) 15%, transparent);
  color: var(--error);
}
.status-pending {
  background: var(--bg-tertiary);
  color: var(--text-muted);
}
</style>
