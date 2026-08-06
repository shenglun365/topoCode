<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PlayIcon, PlusIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import type { TestChannel, UnitTest } from '@/types'
import { useArchUnitTestStore } from '@/stores/unit-test-store'
import UnitTestAddDialog from './UnitTestAddDialog.vue'

const props = defineProps<{ sessionId: string }>()
const { t } = useI18n()
const store = useArchUnitTestStore()

const session = computed(() => store.sessions.find((s) => s.id === props.sessionId))
const includeLinked = ref(true)
const tests = computed(() => (includeLinked.value ? store.tests : []))
const selected = ref<string[]>([])
const channel = ref<TestChannel>('cli')
const addOpen = ref(false)

const statusColor: Record<string, string> = {
  idle: 'bg-ctp-surface0 text-ctp-subtext0',
  running: 'bg-ctp-blue/15 text-ctp-blue',
  passed: 'bg-ctp-green/15 text-ctp-green',
  failed: 'bg-ctp-red/15 text-ctp-red',
  error: 'bg-ctp-red/15 text-ctp-red',
  skipped: 'bg-ctp-overlay0/20 text-ctp-overlay1',
}
const levelColor: Record<string, string> = {
  L0: 'bg-ctp-red/15 text-ctp-red',
  L1: 'bg-ctp-peach/15 text-ctp-peach',
  L2: 'bg-ctp-yellow/15 text-ctp-yellow',
  L3: 'bg-ctp-green/15 text-ctp-green',
  L4: 'bg-ctp-blue/15 text-ctp-blue',
  L5: 'bg-ctp-mauve/15 text-ctp-mauve',
}

function toggleOne(id: string) {
  const i = selected.value.indexOf(id)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(id)
}
function toggleAll() {
  const ids = tests.value.map((t) => t.id)
  selected.value = selected.value.length === ids.length ? [] : ids
}
function runSingle(test: UnitTest) {
  store.channel = channel.value
  store.runTests([test.id])
}
function runSelected() {
  if (!selected.value.length) return
  store.channel = channel.value
  store.runTests([...selected.value])
}
function onAdded() {
  addOpen.value = false
}
</script>

<template>
  <div class="flex flex-col h-full min-h-0 gap-2">
    <!-- 执行通道选择(每次执行可选，默认值) -->
    <div class="shrink-0 flex items-center gap-1.5">
      <span class="text-[11px] text-ctp-overlay1 shrink-0">{{ t('unitTest.channel.label') }}</span>
      <div class="flex gap-1">
        <button
          v-for="c in (['agent', 'cli'] as const)"
          :key="c"
          class="btn btn-xs"
          :class="channel === c ? 'btn-blue' : 'btn-ghost'"
          @click="channel = c"
        >{{ t(`unitTest.channel.${c}`) }}</button>
      </div>
      <button
        class="btn btn-xs btn-ghost ml-auto"
        @click="addOpen = true"
      >
        <PlusIcon class="w-3 h-3" />{{ t('unitTest.addTest') }}
      </button>
    </div>

    <!-- 工具条 -->
    <div class="shrink-0 flex items-center gap-1.5">
      <label class="flex items-center gap-1 text-[11px] text-ctp-overlay1">
        <input
          v-model="includeLinked"
          type="checkbox"
          class="accent-ctp-blue"
        >
        {{ t('unitTest.allTests') }}
      </label>
      <div class="flex-1" />
      <button
        class="btn btn-xs btn-ghost"
        :disabled="store.running"
        @click="runSelected"
      >
        <PlayIcon class="w-3 h-3" />{{ t('unitTest.runSelected', { n: selected.length }) }}
      </button>
    </div>

    <!-- 列表 -->
    <div class="flex-1 min-h-0 overflow-auto flex flex-col">
      <div class="panel">
        <div class="flex-1 min-h-0 overflow-auto">
          <table class="w-full text-left text-xs">
            <thead class="sticky top-0 bg-ctp-mantle text-ctp-overlay1">
              <tr>
                <th class="px-2 py-1.5">
                  <input
                    type="checkbox"
                    class="accent-ctp-blue"
                    :checked="tests.length > 0 && selected.length === tests.length"
                    @change="toggleAll"
                  >
                </th>
                <th class="px-2 py-1.5 font-medium">{{ t('unitTest.colName') }}</th>
                <th class="px-2 py-1.5 font-medium">{{ t('unitTest.colLevels') }}</th>
                <th class="px-2 py-1.5 font-medium">{{ t('unitTest.colStatus') }}</th>
                <th class="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="test in tests"
                :key="test.id"
                class="border-t border-ctp-surface0"
              >
                <td class="px-2 py-1.5">
                  <input
                    type="checkbox"
                    class="accent-ctp-blue"
                    :checked="selected.includes(test.id)"
                    @change="toggleOne(test.id)"
                  >
                </td>
                <td class="px-2 py-1.5">
                  <div class="flex items-center gap-1.5">
                    <span class="truncate">{{ test.name }}</span>
                  </div>
                  <div class="text-[10px] text-ctp-overlay1 font-mono truncate">{{ test.scriptPath }}</div>
                </td>
                <td class="px-2 py-1.5">
                  <div class="flex flex-wrap gap-0.5">
                    <span
                      v-for="l in test.levels"
                      :key="l"
                      class="chip !text-[9px]"
                      :class="levelColor[l]"
                    >{{ l }}</span>
                  </div>
                </td>
                <td class="px-2 py-1.5">
                  <span
                    class="chip"
                    :class="statusColor[test.status]"
                  >{{ t(`unitTest.testStatus.${test.status}`) }}</span>
                </td>
                <td class="px-2 py-1.5">
                  <button
                    class="btn btn-xs btn-green shrink-0"
                    :disabled="store.running"
                    @click="runSingle(test)"
                    @click.stop
                  >
                    <PlayIcon class="w-3 h-3" />{{ t('unitTest.run') }}
                  </button>
                </td>
              </tr>
              <tr v-if="!tests.length">
                <td
                  colspan="5"
                  class="px-3 py-8 text-center text-ctp-overlay0"
                >{{ t('common.empty') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <UnitTestAddDialog
      :open="addOpen"
      @close="addOpen = false"
      @added="onAdded"
    />
  </div>
</template>