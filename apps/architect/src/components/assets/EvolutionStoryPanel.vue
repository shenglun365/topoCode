<script setup lang="ts">
/**
 * 演化播放面板 —— 把架构快照序列（snapshots）转成帧序列交 TopoStory 补间播放。
 * 责任分界（docs/integration-topoOne.md）：快照/head 序列归 architect；动画引擎只吃帧数组。
 * 每个快照的同一视角（structure/dependency/calls）经 diagram-gen 出帧源文，
 * 帧间新增/删除/移动/变形由 @topo/engine keydiff 自动分类补间。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import TopoStory from '@topo/graph-kernel/vue/TopoStory.vue'
import { useArchProjectStore } from '@/stores/project-store'
import { callsToMermaid, componentsToMermaid, structuresToMermaid } from '@/utils/diagram-gen'
import type { ArchitectureModel } from '@/types'

const props = defineProps<{ category: 'structure' | 'dependency' | 'calls' }>()
const { t } = useI18n()
const project = useArchProjectStore()

const theme = ref<'light' | 'dark'>('dark')
onMounted(() => {
  theme.value = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'
})

function gen(m: ArchitectureModel): string {
  if (props.category === 'structure') return structuresToMermaid(m.erTables)
  if (props.category === 'dependency') return componentsToMermaid(m.components)
  return callsToMermaid(m.dataFlows, m.components)
}

const snaps = computed(() => project.snapshots)
const sources = computed(() => snaps.value.map((s) => gen(s.model)))
const frameIds = computed(() => snaps.value.map((s) => s.version || s.id))
const annotations = computed(() =>
  snaps.value.map((s) => ({ commit: s.name || s.version, date: new Date(s.createdAt).toLocaleDateString() })),
)
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="panel-header">
      <span class="flex items-center gap-2 text-xs text-ctp-subtext0">
        <span class="w-2 h-2 rounded-full bg-ctp-teal" />{{ t('archChange.evolution') }}
      </span>
      <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ snaps.length }}</span>
    </div>
    <TopoStory
      v-if="sources.length >= 2"
      :sources="sources"
      :frame-ids="frameIds"
      :annotations="annotations"
      :theme="theme"
      engine="mermaid"
      :step-ms="1400"
    />
    <div
      v-else
      class="px-4 py-8 text-center text-[11px] text-ctp-overlay1"
    >{{ t('archChange.evolutionNeedTwo') }}</div>
  </div>
</template>
