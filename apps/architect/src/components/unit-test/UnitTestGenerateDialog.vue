<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import type { TestLevel } from '@/types'
import { useArchUnitTestStore } from '@/stores/unit-test-store'
import { unitTestService } from '@/services/unit-test-service'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; added: [] }>()
const { t } = useI18n()
const store = useArchUnitTestStore()

const scope = ref('')
const loading = ref(false)
const draft = ref<{ name: string; levels: TestLevel[]; scriptPath: string; desc: string }[]>([])
const selected = ref<Set<number>>(new Set())
const error = ref('')

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
      scope.value = ''
      draft.value = []
      selected.value = new Set()
      error.value = ''
      loading.value = false
    }
  },
)

async function generate() {
  if (!scope.value.trim() || loading.value) return
  loading.value = true
  error.value = ''
  draft.value = []
  try {
    const res = await unitTestService.generateTests(scope.value.trim())
    draft.value = res.tests
    // 默认全选
    selected.value = new Set(res.tests.map((_, i) => i))
  } catch (e: any) {
    error.value = e?.response?.data?.message || e?.message || t('unitTest.generateEmpty')
  } finally {
    loading.value = false
  }
}

function toggle(i: number) {
  const s = new Set(selected.value)
  if (s.has(i)) s.delete(i)
  else s.add(i)
  selected.value = s
}

async function confirm() {
  const tests = draft.value.filter((_, i) => selected.value.has(i))
  if (!tests.length) return
  await store.confirmDraft(tests)
  emit('added')
  emit('close')
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/70"
    @click.self="emit('close')"
  >
    <div class="w-[560px] max-w-[94vw] rounded-xl border border-ctp-surface1 bg-ctp-mantle shadow-xl p-4 space-y-3 max-h-[86vh] overflow-y-auto">
      <div class="flex items-center justify-between">
        <span class="text-sm font-semibold text-ctp-text flex items-center gap-1.5">
          <SparklesIcon class="w-4 h-4 text-ctp-lavender" />{{ t('unitTest.generateTitle') }}
        </span>
        <button class="text-ctp-overlay1 hover:text-ctp-red" @click="emit('close')">
          <XMarkIcon class="w-4 h-4" />
        </button>
      </div>
      <p class="text-[11px] text-ctp-overlay1">{{ t('unitTest.generateHint') }}</p>

      <div>
        <label class="text-[11px] text-ctp-overlay1">{{ t('unitTest.generateScope') }}</label>
        <textarea
          v-model="scope"
          rows="2"
          class="input mt-1 resize-none"
          :placeholder="t('unitTest.generateScopePh')"
        ></textarea>
      </div>

      <div class="flex justify-end gap-2">
        <button class="btn btn-sm btn-ghost" @click="emit('close')">{{ t('common.close') }}</button>
        <button
          class="btn btn-sm btn-blue"
          :disabled="!scope.trim() || loading"
          @click="generate"
        >{{ loading ? t('unitTest.generateLoading') : t('unitTest.generateDo') }}</button>
      </div>

      <!-- 草稿区 -->
      <div v-if="draft.length" class="border-t border-ctp-surface0 pt-3 space-y-2">
        <p class="text-[11px] text-ctp-overlay1">{{ t('unitTest.generateDraft', { n: draft.length }) }}</p>
        <div class="space-y-1.5">
          <label
            v-for="(d, i) in draft"
            :key="i"
            class="flex items-start gap-2 rounded-lg border border-ctp-surface0 bg-ctp-crust/40 p-2 cursor-pointer hover:border-ctp-surface1"
          >
            <input
              type="checkbox"
              class="mt-0.5"
              :checked="selected.has(i)"
              @change="toggle(i)"
            >
            <div class="flex-1 min-w-0">
              <div class="text-xs text-ctp-text font-medium">{{ d.name }}</div>
              <div v-if="d.scriptPath" class="text-[10px] font-mono text-ctp-overlay1 truncate">{{ d.scriptPath }}</div>
              <div v-if="d.desc" class="text-[10px] text-ctp-overlay0 mt-0.5">{{ d.desc }}</div>
              <div class="mt-1 flex flex-wrap gap-1">
                <span
                  v-for="l in d.levels"
                  :key="l"
                  class="text-[9px] px-1 rounded"
                  :class="levelColor[l] || 'bg-ctp-surface0 text-ctp-subtext0'"
                >{{ l }}</span>
              </div>
            </div>
          </label>
        </div>
        <div class="flex justify-end gap-2 pt-1">
          <button class="btn btn-sm btn-ghost" @click="emit('close')">{{ t('common.close') }}</button>
          <button
            class="btn btn-sm btn-blue"
            :disabled="!selected.size"
            @click="confirm"
          >{{ t('unitTest.generateConfirm', { n: selected.size }) }}</button>
        </div>
      </div>

      <p v-if="error" class="text-[11px] text-ctp-red">{{ error }}</p>
    </div>
  </div>
</template>
