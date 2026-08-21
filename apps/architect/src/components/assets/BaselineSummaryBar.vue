<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { TagIcon, ChevronDownIcon, ChevronUpIcon, ScaleIcon, CalendarIcon, ArchiveBoxIcon, CodeBracketIcon } from '@heroicons/vue/24/outline'
import { currentBaselineInfo } from '@/services/baseline-service'

const { t } = useI18n()
const info = currentBaselineInfo()
const open = ref(false)

const fmt = (ts: number) => new Date(ts).toLocaleString()

const fields = computed(() => [
  { icon: TagIcon, label: t('baseline.gitTag'), value: info.gitTag, color: 'text-ctp-mauve' },
  { icon: ScaleIcon, label: t('baseline.branch'), value: info.branch, color: 'text-ctp-sky' },
  { icon: CalendarIcon, label: t('baseline.gitDate'), value: fmt(info.gitDate), color: 'text-ctp-teal' },
  { icon: CalendarIcon, label: t('baseline.analyzedAt'), value: fmt(info.analyzedAt), color: 'text-ctp-lavender' },
  { icon: ArchiveBoxIcon, label: t('baseline.archVersion'), value: info.archVersion, color: 'text-ctp-peach' },
  { icon: CodeBracketIcon, label: t('baseline.commit'), value: info.commit || '—', color: 'text-ctp-subtext1' },
])
</script>

<template>
  <div class="panel overflow-hidden">
    <div
      class="panel-header cursor-pointer select-none"
      @click="open = !open"
    >
      <span class="flex items-center gap-2">
        <ArchiveBoxIcon class="w-4 h-4 text-ctp-mauve" />{{ t('baseline.title') }}
        <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono">{{ info.gitTag }}</span>
      </span>
      <span class="flex items-center gap-2">
        <span class="text-[11px] text-ctp-overlay1">
          {{ open ? t('baseline.collapse') : t('baseline.expand') }}
        </span>
        <component
          :is="open ? ChevronUpIcon : ChevronDownIcon"
          class="w-3.5 h-3.5 text-ctp-overlay0"
        />
      </span>
    </div>

    <template v-if="open">
      <div class="p-4 border-t border-ctp-surface0">
        <p class="text-xs text-ctp-subtext1 mb-3">
          {{ info.desc }}
        </p>
        <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
          <div
            v-for="f in fields"
            :key="f.label"
            class="flex items-center gap-2 border border-ctp-surface0 rounded-lg px-3 py-2"
          >
            <component
              :is="f.icon"
              class="w-4 h-4 shrink-0"
              :class="f.color"
            />
            <div class="min-w-0">
              <div class="text-[10px] uppercase tracking-wider text-ctp-overlay1">
                {{ f.label }}
              </div>
              <div class="text-xs text-ctp-text truncate">
                {{ f.value }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
