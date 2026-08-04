<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CubeIcon, XMarkIcon, MagnifyingGlassIcon } from '@heroicons/vue/24/outline'
import { useArchRequirementStore } from '@/stores/requirement-store'

const props = defineProps<{
  open: boolean
  selected: string[]
  title?: string
  hint?: string
}>()
const emit = defineEmits<{
  'update:open': [v: boolean]
  confirm: [ids: string[]]
}>()

const { t } = useI18n()
const requirement = useArchRequirementStore()
const query = ref('')
const picked = ref<string[]>([])

watch(
  () => props.open,
  (v) => {
    if (v) {
      picked.value = [...props.selected]
      query.value = ''
    }
  },
)

const prioColor: Record<string, string> = {
  P0: 'bg-ctp-red/15 text-ctp-red',
  P1: 'bg-ctp-peach/15 text-ctp-peach',
  P2: 'bg-ctp-overlay0/20 text-ctp-overlay1',
}

const list = computed(() => {
  const q = query.value.trim().toLowerCase()
  return [...requirement.poolItems]
    .sort((a, b) => (a.priority === 'P0' ? 0 : a.priority === 'P1' ? 1 : 2) - (b.priority === 'P0' ? 0 : b.priority === 'P1' ? 1 : 2))
    .filter((r) => !q || r.id.toLowerCase().includes(q) || r.title.toLowerCase().includes(q))
})

function toggle(id: string) {
  const i = picked.value.indexOf(id)
  if (i >= 0) picked.value.splice(i, 1)
  else picked.value.push(id)
}
function confirm() {
  emit('confirm', [...picked.value])
  emit('update:open', false)
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
    @click.self="emit('update:open', false)"
  >
    <div class="panel w-full max-w-lg max-h-[70vh] overflow-hidden flex flex-col">
      <div class="panel-header shrink-0">
        <span class="flex items-center gap-2">
          <CubeIcon class="w-4 h-4 text-ctp-green" />{{ title ?? t('execute.selectReq') }}
        </span>
        <span class="text-[11px] text-ctp-overlay1">{{ picked.length }}</span>
        <button
          class="btn btn-xs btn-ghost"
          @click="emit('update:open', false)"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      <div class="p-3 flex flex-col gap-2 min-h-0 flex-1">
        <div class="relative">
          <MagnifyingGlassIcon class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-ctp-overlay0" />
          <input
            v-model="query"
            class="input pl-8 !py-1.5 text-xs"
            :placeholder="t('execute.poolSearch')"
          >
        </div>
        <p
          v-if="hint"
          class="text-[10px] text-ctp-overlay1 -mt-1"
        >
          {{ hint }}
        </p>
        <div class="min-h-0 overflow-auto space-y-1">
          <button
            v-for="r in list"
            :key="r.id"
            class="w-full flex items-center gap-2 px-2 py-1.5 rounded text-left transition-colors"
            :class="picked.includes(r.id) ? 'bg-ctp-surface0 ring-1 ring-ctp-blue/40' : 'hover:bg-ctp-surface0/60'"
            @click="toggle(r.id)"
          >
            <input
              type="checkbox"
              class="accent-ctp-green shrink-0 pointer-events-none"
              :checked="picked.includes(r.id)"
            >
            <span class="font-mono text-[10px] text-ctp-overlay1 shrink-0">{{ r.id }}</span>
            <span class="text-xs text-ctp-text truncate flex-1">{{ r.title }}</span>
            <span
              class="chip shrink-0"
              :class="prioColor[r.priority]"
            >{{ r.priority }}</span>
          </button>
          <p
            v-if="!list.length"
            class="text-xs text-ctp-overlay0 text-center py-6"
          >
            {{ t('common.empty') }}
          </p>
        </div>
      </div>
      <div class="shrink-0 border-t border-ctp-surface0 p-2.5 flex justify-end">
        <button
          class="btn btn-sm btn-green"
          :disabled="!picked.length"
          @click="confirm"
        >
          <CubeIcon class="w-3.5 h-3.5" />{{ t('execute.poolPickConfirm', { n: picked.length }) }}
        </button>
      </div>
    </div>
  </div>
</template>
