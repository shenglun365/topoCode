<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ClockIcon, ChevronDownIcon, ChevronUpIcon, ArrowsRightLeftIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import { useArchKbQueryStore } from '@/stores/kb-query-store'

const { t } = useI18n()
const kb = useArchKbQueryStore()
kb.load()

const expanded = ref<string | null>(null)

const sorted = computed(() => [...kb.history].sort((a, b) => b.createdAt - a.createdAt))

const fmt = (ts: number) => new Date(ts).toLocaleString()

function toggle(id: string) {
  expanded.value = expanded.value === id ? null : id
}

watch(
  () => kb.history.length,
  () => {
    if (!expanded.value) expanded.value = sorted.value[0]?.id ?? null
  },
  { immediate: true },
)
</script>

<template>
  <div class="space-y-4">
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <ClockIcon class="w-4 h-4 text-ctp-teal" />{{ t('kbQuery.history.title') }}
        </span>
        <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ sorted.length }}</span>
      </div>
      <div class="p-4">
        <p class="text-xs text-ctp-subtext0">
          {{ t('kbQuery.history.desc') }}
        </p>
      </div>
    </div>

    <div
      v-if="!sorted.length"
      class="panel p-8 text-center"
    >
      <ClockIcon class="w-8 h-8 text-ctp-overlay0 mx-auto mb-2" />
      <p class="text-xs text-ctp-overlay1">
        {{ t('kbQuery.history.empty') }}
      </p>
    </div>

    <div
      v-for="h in sorted"
      :key="h.id"
      class="panel overflow-hidden"
    >
      <div
        class="panel-header cursor-pointer select-none"
        @click="toggle(h.id)"
      >
        <span class="flex items-center gap-2 min-w-0">
          <component
            :is="h.spec.kind === 'depends' ? ArrowsRightLeftIcon : SparklesIcon"
            class="w-4 h-4 shrink-0"
            :class="h.spec.kind === 'depends' ? 'text-ctp-sky' : 'text-ctp-mauve'"
          />
          <span class="text-sm font-medium text-ctp-text truncate">
            {{ h.spec.kind === 'depends' ? t('kbQuery.depends') : t('kbQuery.calls') }}
            : {{ h.spec.compIds.join(', ') }}
          </span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0 shrink-0 font-mono">{{ h.baselineTag }}</span>
          <span
            v-if="h.cached"
            class="chip bg-ctp-green/15 text-ctp-green shrink-0"
          >{{ t('kbQuery.cached') }}</span>
        </span>
        <span class="flex items-center gap-2">
          <span class="text-[11px] text-ctp-overlay1 shrink-0">{{ fmt(h.createdAt) }}</span>
          <component
            :is="expanded === h.id ? ChevronUpIcon : ChevronDownIcon"
            class="w-3.5 h-3.5 text-ctp-overlay0 shrink-0"
          />
        </span>
      </div>
      <div
        v-if="expanded === h.id"
        class="p-4 text-xs text-ctp-subtext1"
      >
        <div class="flex flex-wrap gap-1.5 mb-2">
          <span
            v-for="s in h.spec.sections"
            :key="s"
            class="chip bg-ctp-surface0 text-ctp-subtext0"
          >{{ t(`kbQuery.sections.${s}`) }}</span>
          <span
            v-if="h.spec.note"
            class="chip bg-ctp-peach/10 text-ctp-peach"
          >{{ h.spec.note }}</span>
        </div>
        <p>
          {{ h.summary }}
        </p>
      </div>
    </div>
  </div>
</template>
