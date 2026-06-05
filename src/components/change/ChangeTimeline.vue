<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CheckCircleIcon,
  ClockIcon,
  DocumentTextIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
import { useChangeStore } from '@/stores/change-store'

const { showId, componentId } = useComponentId('CH-003')
const { t } = useI18n()
const store = useChangeStore()

const emit = defineEmits<{
  compare: [from: string, to: string]
}>()

const timelineCommits = computed(() => store.commits.slice(0, 30))

function formatDate(timestamp: string): string {
  const d = new Date(timestamp)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function onCommitClick(hash: string) {
  const idx = store.commits.findIndex(c => c.hash === hash)
  if (idx >= 0 && idx < store.commits.length - 1) {
    emit('compare', store.commits[idx + 1].hash, hash)
  }
}
</script>

<template>
  <div class="change-timeline">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="timeline-header">
      <span class="timeline-title">{{ t('change.commitHistory') }}</span>
      <span class="timeline-count">{{ store.commits.length }} {{ t('change.commits') }}</span>
    </div>
    <div class="timeline-list">
      <div
        v-for="(c, i) in timelineCommits"
        :key="c.hash"
        class="timeline-item"
        :class="{ 'timeline-item-active': c.hash === store.selectedToCommit }"
        @click="onCommitClick(c.hash)"
      >
        <div class="timeline-line">
          <div
            v-if="i === 0"
            class="timeline-dot timeline-dot-head"
          >
            <CheckCircleIcon class="w-3 h-3" />
          </div>
          <div
            v-else
            class="timeline-dot"
            :class="{ 'has-snapshot': c.hasSnapshot }"
          />
          <div
            v-if="i < timelineCommits.length - 1"
            class="timeline-connector"
          />
        </div>
        <div class="timeline-content">
          <div class="timeline-message">
            {{ c.message }}
          </div>
          <div class="timeline-meta">
            <span class="timeline-hash">{{ c.hash.substring(0, 8) }}</span>
            <span class="timeline-separator">·</span>
            <span class="timeline-date">{{ formatDate(c.timestamp) }}</span>
            <span class="timeline-separator">·</span>
            <span class="timeline-author">{{ c.author }}</span>
            <DocumentTextIcon
              v-if="c.hasSnapshot"
              class="timeline-snapshot-icon w-3 h-3"
              :title="t('change.snapshotAvailable')"
            />
            <ClockIcon
              v-else
              class="timeline-no-snapshot-icon w-3 h-3"
              :title="t('change.noSnapshot')"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.change-timeline {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}

.timeline-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.timeline-count {
  font-size: 11px;
  color: var(--text-muted);
}

.timeline-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.timeline-item {
  display: flex;
  gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  transition: background 0.1s;
}

.timeline-item:hover {
  background: var(--bg-hover);
}

.timeline-item-active {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border-right: 2px solid var(--accent);
}

.timeline-line {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 16px;
  flex-shrink: 0;
}

.timeline-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--border);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.timeline-dot-head {
  background: var(--accent);
  color: #fff;
  width: 16px;
  height: 16px;
}

.has-snapshot {
  background: var(--accent);
}

.timeline-connector {
  width: 1px;
  flex: 1;
  background: var(--border);
  margin: 2px 0;
}

.timeline-content {
  flex: 1;
  min-width: 0;
}

.timeline-message {
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
}

.timeline-hash {
  font-family: monospace;
}

.timeline-separator {
  color: var(--border);
}

.timeline-snapshot-icon {
  color: var(--accent);
  flex-shrink: 0;
}

.timeline-no-snapshot-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}
</style>
