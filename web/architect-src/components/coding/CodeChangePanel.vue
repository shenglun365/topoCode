<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDownIcon, ChevronRightIcon, DocumentTextIcon } from '@heroicons/vue/24/outline'
import { useArchGitSyncStore } from '@/stores/git-sync-store'

const { t } = useI18n()
const data = useArchGitSyncStore()
const open = ref(false)

const statusColor: Record<string, string> = {
  A: 'text-ctp-green',
  M: 'text-ctp-peach',
  D: 'text-ctp-red',
  R: 'text-ctp-sky',
}
const statusLabel: Record<string, string> = { A: '+', M: '~', D: '-', R: '→' }

onMounted(() => {
  data.loadChanges()
})

const addTotal = () => data.changes?.files.reduce((s, f) => s + f.add, 0) ?? 0
const delTotal = () => data.changes?.files.reduce((s, f) => s + f.del, 0) ?? 0
</script>

<template>
  <div>
    <div class="flex items-center gap-2">
      <DocumentTextIcon class="w-3.5 h-3.5 text-ctp-sky" />
      <span class="text-[11px] font-medium text-ctp-subtext1">{{ t('execute.changes') }}</span>
      <button
        class="shrink-0 text-ctp-overlay0 hover:text-ctp-text"
        @click="open = !open"
      >
        <component
          :is="open ? ChevronDownIcon : ChevronRightIcon"
          class="w-3.5 h-3.5"
        />
      </button>
      <span class="ml-auto text-[10px] text-ctp-overlay1">
        <template v-if="data.changes">
          {{ data.changes.files.length }} {{ t('execute.changesFiles') }} · <span class="text-ctp-green">+{{ addTotal() }}</span>/<span class="text-ctp-red">-{{ delTotal() }}</span>
        </template>
      </span>
    </div>
    <div
      v-if="open && data.changes"
      class="mt-2 space-y-1"
    >
      <div
        v-for="f in data.changes.files"
        :key="f.path"
        class="flex items-center gap-2 text-[11px]"
      >
        <span
          class="w-4 shrink-0 font-mono"
          :class="statusColor[f.status]"
        >{{ statusLabel[f.status] }}</span>
        <span class="truncate font-mono text-ctp-sapphire">{{ f.path }}</span>
        <span class="ml-auto shrink-0 text-[10px] text-ctp-overlay1">+{{ f.add }}/-{{ f.del }}</span>
      </div>
    </div>
  </div>
</template>
