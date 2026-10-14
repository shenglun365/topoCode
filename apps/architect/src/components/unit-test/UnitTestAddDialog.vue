<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import type { TestLevel } from '@/types'
import { useArchUnitTestStore } from '@/stores/unit-test-store'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; added: [] }>()
const { t } = useI18n()
const store = useArchUnitTestStore()

const name = ref('')
const scriptPath = ref('')
const levels = ref<TestLevel[]>([])

const LEVELS: TestLevel[] = ['L0', 'L1', 'L2', 'L3', 'L4', 'L5']
const levelColor: Record<string, string> = {
  L0: 'bg-ctp-red/15 text-ctp-red',
  L1: 'bg-ctp-peach/15 text-ctp-peach',
  L2: 'bg-ctp-yellow/15 text-ctp-yellow',
  L3: 'bg-ctp-green/15 text-ctp-green',
  L4: 'bg-ctp-blue/15 text-ctp-blue',
  L5: 'bg-ctp-mauve/15 text-ctp-mauve',
}

watch(
  () => props.open,
  (v) => {
    if (v) {
      name.value = ''
      scriptPath.value = ''
      levels.value = []
    }
  },
)

function toggleLevel(l: TestLevel) {
  const i = levels.value.indexOf(l)
  if (i >= 0) levels.value.splice(i, 1)
  else levels.value.push(l)
}

async function submit() {
  if (!name.value.trim()) return
  await store.addTest({ name: name.value.trim(), scriptPath: scriptPath.value.trim(), levels: [...levels.value] })
  emit('added')
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/70"
    @click.self="emit('close')"
  >
    <div class="w-[480px] max-w-[92vw] rounded-xl border border-ctp-surface1 bg-ctp-mantle shadow-xl p-4 space-y-3">
      <div class="flex items-center justify-between">
        <span class="text-sm font-semibold text-ctp-text">{{ t('unitTest.addTitle') }}</span>
        <button
          class="text-ctp-overlay1 hover:text-ctp-red"
          @click="emit('close')"
        >
          <XMarkIcon class="w-4 h-4" />
        </button>
      </div>
      <p class="text-[11px] text-ctp-overlay1">{{ t('unitTest.addHint') }}</p>

      <div>
        <label class="text-[11px] text-ctp-overlay1">{{ t('unitTest.addName') }}</label>
        <input
          v-model="name"
          class="input mt-1"
          :placeholder="t('unitTest.addNamePh')"
        >
      </div>

      <div>
        <label class="text-[11px] text-ctp-overlay1">{{ t('unitTest.addPath') }}</label>
        <input
          v-model="scriptPath"
          class="input mt-1 font-mono"
          :placeholder="t('unitTest.addPathPh')"
        >
      </div>

      <div>
        <label class="text-[11px] text-ctp-overlay1">{{ t('unitTest.colLevels') }}</label>
        <div class="mt-1 flex flex-wrap gap-1">
          <button
            v-for="l in LEVELS"
            :key="l"
            class="chip cursor-pointer"
            :class="levels.includes(l) ? levelColor[l] : 'bg-ctp-surface0 text-ctp-subtext0'"
            @click="toggleLevel(l)"
          >{{ l }}</button>
        </div>
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <button
          class="btn btn-sm btn-ghost"
          @click="emit('close')"
        >{{ t('common.close') }}</button>
        <button
          class="btn btn-sm btn-blue"
          :disabled="!name.trim()"
          @click="submit"
        >{{ t('unitTest.addConfirm') }}</button>
      </div>
    </div>
  </div>
</template>