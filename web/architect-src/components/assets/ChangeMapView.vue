<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { TableCellsIcon, ShareIcon, ChatBubbleLeftRightIcon, DocumentTextIcon } from '@heroicons/vue/24/outline'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import CodeChangeModal from './CodeChangeModal.vue'
import type { ArchChangeReport, CodeChangeItem } from '@/services/arch-change-service'

const props = defineProps<{ report: ArchChangeReport | null }>()
const { t } = useI18n()

type MapCategory = 'structure' | 'dependency' | 'calls'
const active = ref<MapCategory>('structure')

const tabs = [
  { key: 'structure', icon: TableCellsIcon },
  { key: 'dependency', icon: ShareIcon },
  { key: 'calls', icon: ChatBubbleLeftRightIcon },
] as const

const currentDiagram = computed(() => {
  if (!props.report) return {}
  return { mermaid: props.report.diagrams[active.value] ?? '' }
})
const currentTitle = computed(() => t(`archChange.mapTitle.${active.value}`))
const currentBadge = computed(() => ({ text: t(`archChange.mapKind.${active.value}`), cls: 'bg-ctp-surface0 text-ctp-subtext0' }))

/** 每类图对应的代码变更摘要(按 category 过滤)。 */
const filteredChanges = computed<CodeChangeItem[]>(() => {
  if (!props.report) return []
  return props.report.codeChanges.filter((c) => c.category === active.value)
})

const selected = ref<CodeChangeItem | null>(null)
</script>

<template>
  <div class="space-y-4">
    <!-- 图类型切换 -->
    <div class="flex items-center gap-1 bg-ctp-crust/60 rounded-lg p-1 w-fit">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors"
        :class="active === tab.key ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
        @click="active = tab.key"
      >
        <component
          :is="tab.icon"
          class="w-4 h-4"
        />{{ t(`archChange.mapTitle.${tab.key}`) }}
      </button>
    </div>

    <!-- 当前图 -->
    <DiagramCard
      :title="currentTitle"
      :diagrams="currentDiagram"
      :badges="[currentBadge]"
    />

    <!-- 对应代码变更摘要列表 -->
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <DocumentTextIcon class="w-4 h-4 text-ctp-blue" />{{ t('archChange.codeChanges') }}
        </span>
        <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ filteredChanges.length }}</span>
      </div>
      <div class="p-2 divide-y divide-ctp-surface0">
        <button
          v-for="c in filteredChanges"
          :key="c.id"
          class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-ctp-surface0/50 rounded-md cursor-pointer"
          @click="selected = c"
        >
          <span
            class="chip shrink-0"
            :class="c.change === 'added' ? 'bg-ctp-green/15 text-ctp-green' : c.change === 'modified' ? 'bg-ctp-peach/15 text-ctp-peach' : 'bg-ctp-red/15 text-ctp-red'"
          >{{ c.change === 'added' ? '+' : c.change === 'modified' ? '~' : '−' }}</span>
          <div class="flex-1 min-w-0">
            <div class="text-xs text-ctp-text truncate">
              {{ c.title }}
            </div>
            <div class="text-[11px] text-ctp-overlay1 truncate">
              {{ c.summary }} · {{ c.file }}
            </div>
          </div>
          <span class="text-[11px] text-ctp-blue shrink-0">{{ t('archChange.viewCode') }} →</span>
        </button>
        <div
          v-if="!filteredChanges.length"
          class="px-3 py-4 text-[11px] text-ctp-overlay1 text-center"
        >
          {{ t('archChange.noChanges') }}
        </div>
      </div>
    </div>

    <Teleport to="body">
      <CodeChangeModal
        :item="selected"
        @close="selected = null"
      />
    </Teleport>
  </div>
</template>