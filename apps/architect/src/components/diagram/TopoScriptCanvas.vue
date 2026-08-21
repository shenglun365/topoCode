<script setup lang="ts">
import { computed } from 'vue'
import { parseTopoScript } from '@/composables/useTopoScript'
import type { TsGraph, TsNode } from '@/composables/useTopoScript'

const props = defineProps<{ code: string; playing: boolean }>()

const graph = computed<TsGraph>(() => parseTopoScript(props.code))
const positions = computed(() => {
  const n = graph.value.nodes.length
  const cols = Math.ceil(Math.sqrt(n))
  const map = new Map<string, { x: number; y: number }>()
  graph.value.nodes.forEach((node, i) => {
    map.set(node.id, { x: 60 + (i % cols) * 240, y: 60 + Math.floor(i / cols) * 140 })
  })
  return map
})

const size = computed(() => {
  const cols = Math.ceil(Math.sqrt(graph.value.nodes.length))
  const rows = Math.ceil(graph.value.nodes.length / cols)
  return { w: Math.max(460, cols * 240 + 120), h: Math.max(240, rows * 140 + 120) }
})

const flows = computed(() => {
  const out: { from: TsNode; to: TsNode; label: string }[] = []
  for (const link of graph.value.links) {
    const from = graph.value.nodes.find((n) => n.id === link.from)
    const to = graph.value.nodes.find((n) => n.id === link.to)
    if (from && to) out.push({ from, to, label: link.label })
  }
  return out
})

function linkPath(i: number) {
  const f = flows.value[i]
  if (!f) return ''
  const a = positions.value.get(f.from.id)!
  const b = positions.value.get(f.to.id)!
  const dy = b.y - a.y
  const dx = b.x - a.x
  const mx = a.x + dx / 2
  const my = a.y + dy / 2 + (dx === 0 ? 50 : 0)
  return `M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`
}
</script>

<template>
  <svg
    :width="size.w"
    :height="size.h"
    class="w-full bg-ctp-crust/40 rounded-md border border-ctp-surface0"
  >
    <defs>
      <marker
        id="topo-arrow"
        viewBox="0 0 10 10"
        refX="9"
        refY="5"
        markerWidth="6"
        markerHeight="6"
        orient="auto-start-reverse"
      >
        <path
          d="M 0 0 L 10 5 L 0 10 z"
          fill="#6c7086"
        />
      </marker>
    </defs>

    <template
      v-for="(_, i) in flows"
      :key="i"
    >
      <path
        :id="`topo-path-${i}`"
        :d="linkPath(i)"
        fill="none"
        stroke="#585b70"
        stroke-width="1.5"
        marker-end="url(#topo-arrow)"
      />
      <circle
        v-if="playing"
        r="3.5"
        fill="#89dceb"
        :class="{ 'animate-pulse': true }"
        :style="{ animationDuration: `${2.2 + (i % 3) * 0.6}s` }"
      >
        <animateMotion
          :dur="`${2.4 + i * 0.4}s`"
          repeatCount="indefinite"
          keyPoints="0;1;0"
          keyTimes="0;0.5;1"
          calcMode="linear"
        >
          <mpath :href="`#topo-path-${i}`" />
        </animateMotion>
      </circle>
    </template>

    <g
      v-for="node in graph.nodes"
      :key="node.id"
    >
      <rect
        :x="positions.get(node.id)!.x - 80"
        :y="positions.get(node.id)!.y - 24"
        width="160"
        height="48"
        rx="8"
        class="fill-ctp-surface0 stroke-ctp-surface2"
        :class="{ 'animate-pulse': playing }"
      />
      <text
        :x="positions.get(node.id)!.x"
        :y="positions.get(node.id)!.y - 1"
        text-anchor="middle"
        class="fill-ctp-text"
        font-size="12"
        font-weight="600"
      >
        {{ node.label }}
      </text>
      <text
        :x="positions.get(node.id)!.x"
        :y="positions.get(node.id)!.y + 15"
        text-anchor="middle"
        class="fill-ctp-overlay0"
        font-size="9"
      >
        :: {{ node.kind }}
      </text>
    </g>
  </svg>
</template>
