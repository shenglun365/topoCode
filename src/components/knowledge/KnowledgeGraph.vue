<script setup lang="ts">
/** 知识图谱 - 使用 D3ForceGraph 渲染 (Worker 计算布局) */

import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import D3ForceGraph from '@/components/visualization/D3ForceGraph.vue'
import MermaidViewer from '@/components/visualization/MermaidViewer.vue'
import {
  CodeBracketIcon,
  CircleStackIcon,
  LightBulbIcon,
} from '@heroicons/vue/24/outline'
import type { KnowledgeGraphNode, KnowledgeGraphEdge } from '@/utils/mock'
import { mockGraphNodes, mockGraphEdges } from '@/utils/mock'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('KN-003')
const { t } = useI18n()

const viewMode = ref<'d3' | 'mermaid'>('d3')

// 原始数据
const rawNodes = ref<KnowledgeGraphNode[]>(mockGraphNodes)
const rawEdges = ref<KnowledgeGraphEdge[]>(mockGraphEdges)

// 转换为 D3 格式
const d3Nodes = computed(() => rawNodes.value.map(n => ({
  id: n.id,
  label: n.label,
  group: n.type,
})))

const d3Edges = computed(() => rawEdges.value.map(e => ({
  source: e.from,
  target: e.to,
  type: e.type,
})))

// 转换为 Mermaid 格式
const mermaidCode = computed(() => {
  let code = 'graph TD\n'

  // 定义节点样式
  for (const node of rawNodes.value) {
    const shape = getNodeShape(node.type)
    code += `    ${node.id}["${node.label}"]\n`
  }

  // 定义边
  for (const edge of rawEdges.value) {
    const arrow = edge.type === 'dependency' ? '===' : '-.-'
    code += `    ${edge.from}${arrow}${edge.to}\n`
  }

  return code
})

function getNodeShape(type: string): string {
  switch (type) {
    case 'module': return '([Module])'
    case 'class': return '[Class]'
    case 'function': return '{Function}'
    case 'knowledge': return '((Knowledge))'
    default: return '[Default]'
  }
}

const viewModes = [
  { id: 'd3' as const, label: computed(() => t('visualization.forceDirected')), icon: CircleStackIcon },
  { id: 'mermaid' as const, label: computed(() => t('visualization.flowChart')), icon: CodeBracketIcon },
]
</script>

<template>
  <div class="knowledge-graph">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 视图切换 -->
    <div class="view-switcher">
      <button
        v-for="mode in viewModes"
        :key="mode.id"
        class="view-btn"
        :class="{ active: viewMode === mode.id }"
        @click="viewMode = mode.id"
      >
        <component
          :is="mode.icon"
          class="w-4 h-4"
        />
        <span>{{ mode.label }}</span>
      </button>

      <div class="view-info">
        <LightBulbIcon class="w-4 h-4" />
        <span>{{ rawNodes.length }} {{ t('visualization.nodes') }} / {{ rawEdges.length }} {{ t('visualization.edges') }}</span>
      </div>
    </div>

    <!-- 图例 -->
    <div class="graph-legend">
      <span>● {{ t('visualization.module') }}</span>
      <span>◼ {{ t('visualization.class') }}</span>
      <span>△ {{ t('visualization.function') }}</span>
      <span>◇ {{ t('visualization.knowledge') }}</span>
      <span>─→ {{ t('visualization.dependency') }}</span>
      <span>┄→ {{ t('visualization.reference') }}</span>
    </div>

    <!-- 渲染区 -->
    <div class="graph-content">
      <!-- D3 力导向图 -->
      <D3ForceGraph
        v-if="viewMode === 'd3'"
        :nodes="d3Nodes"
        :edges="d3Edges"
        :show-toolbar="false"
        :show-labels="true"
        :node-colors="{
          module: '#a6e3a1',
          class: '#f9e2af',
          function: '#f38ba8',
          knowledge: '#cba6f7',
          default: '#89b4fa',
        }"
      />

      <!-- Mermaid 流程图 -->
      <MermaidViewer
        v-else
        :diagram="mermaidCode"
        :show-toolbar="false"
        :cache="true"
      />
    </div>
  </div>
</template>

<style scoped>
.knowledge-graph {
  width: 100%;
  height: 100%;
  position: relative;
  display: flex;
  flex-direction: column;
}

.view-switcher {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 5;
  display: flex;
  gap: 4px;
  align-items: center;
}

.view-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.15s;
}

.view-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.view-btn.active {
  color: var(--accent);
  border-color: var(--accent);
  background: rgba(137, 180, 250, 0.1);
}

.view-info {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
  margin-left: 8px;
  padding: 4px 8px;
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
}

.graph-legend {
  position: absolute;
  bottom: 12px;
  left: 12px;
  z-index: 5;
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  padding: 6px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
}

.graph-content {
  flex: 1;
  overflow: hidden;
}
</style>
