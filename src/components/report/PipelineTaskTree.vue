<script setup lang="ts">
import { computed } from 'vue'
import {
  CheckCircleIcon,
  ClockIcon,
  XCircleIcon,
  ArrowPathIcon,
  MinusCircleIcon,
} from '@heroicons/vue/24/outline'
import type { PipelineTaskNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const props = defineProps<{
  node: PipelineTaskNode
  depth?: number
}>()

const emit = defineEmits<{
  action: [nodeId: string]
  openCommunityAnalysis: []
}>()

const indent = computed(() => (props.depth || 0) * 16)

const { showId, componentId } = useComponentId('RP-009')

function statusIcon(status: string) {
  switch (status) {
    case 'completed': return CheckCircleIcon
    case 'running': return ArrowPathIcon
    case 'error': return XCircleIcon
    case 'skipped': return MinusCircleIcon
    default: return ClockIcon
  }
}
</script>

<template>
  <div
    class="pipeline-task-node"
    :style="{ paddingLeft: indent + 'px' }"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      :class="['node-row', `node-${node.status}`, { 'node-clickable': node.id === 'community_analysis' }]"
      @click="node.id === 'community_analysis' ? emit('openCommunityAnalysis') : undefined"
    >
      <Component
        :is="statusIcon(node.status)"
        :class="['node-icon', `icon-${node.status}`]"
      />
      <div class="node-body">
        <div class="node-header">
          <span class="node-label">{{ node.label }}</span>
          <span class="node-header-right">
            <span
              v-if="node.type === 'group' && node.children"
              class="node-progress-text"
            >
              {{ node.progress }}%
            </span>
            <slot
              name="actions"
              :node="node"
            />
          </span>
        </div>
        <div
          v-if="(node.type === 'group' && node.children) || node.status === 'running' || node.status === 'completed'"
          class="node-progress-bar"
        >
          <div
            :class="['progress-fill', { 'progress-indeterminate': node.status === 'running' && !node.children }]"
            :style="(node.type === 'group' || !node.children) ? { width: (node.status === 'completed' ? 100 : (node.progress || 0)) + '%' } : {}"
          />
        </div>
        <slot
          name="content"
          :node="node"
        />
        <div
          v-if="node.error"
          class="node-error"
        >
          {{ node.error }}
        </div>
      </div>
    </div>
    <div
      v-if="node.children && node.children.length > 0"
      class="node-children"
    >
      <PipelineTaskTree
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :depth="(depth || 0) + 1"
        @action="emit('action', $event)"
        @open-community-analysis="emit('openCommunityAnalysis')"
      >
        <template #actions="{ node: childNode }">
          <slot
            name="actions"
            :node="childNode"
          />
        </template>
        <template #content="{ node: childNode }">
          <slot
            name="content"
            :node="childNode"
          />
        </template>
      </PipelineTaskTree>
    </div>
  </div>
</template>

<style scoped>
.pipeline-task-node {
  display: flex;
  flex-direction: column;
}

.node-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 11px;
}

.node-row:hover {
  background: var(--bg-tertiary);
}

.node-clickable { cursor: pointer; }

.node-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  margin-top: 2px;
}

.icon-completed { color: var(--success); }
.icon-running { color: var(--accent); animation: spin 1s linear infinite; }
.icon-error { color: var(--error); }
.icon-pending { color: var(--text-muted); }
.icon-skipped { color: var(--text-muted); opacity: 0.5; }

.node-body {
  flex: 1;
  min-width: 0;
}

.node-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.node-header-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.node-label {
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 500;
}

.node-progress-text {
  font-size: 9px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.node-progress-bar {
  width: 100%;
  height: 3px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 2px;
}

.node-progress-bar .progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.progress-indeterminate {
  width: 40% !important;
  animation: progressIndeterminate 1.5s ease-in-out infinite;
}

@keyframes progressIndeterminate {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}

.node-error {
  font-size: 9px;
  color: var(--error);
  margin-top: 2px;
}

.node-children {
  display: flex;
  flex-direction: column;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
