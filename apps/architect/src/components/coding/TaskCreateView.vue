<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, CubeIcon, RocketLaunchIcon, SparklesIcon, ArrowRightIcon, ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import { useArchAgentStore } from '@/stores/agent-store'
import { useArchTaskStore } from '@/stores/task-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { commitBatch } from '@/services/execution-batch'
import type { ExecutionTask } from '@/types'
import PoolSelectDialog from '@/components/coding/PoolSelectDialog.vue'

const props = defineProps<{ preselect?: string[] }>()
const emit = defineEmits<{
  created: [exec: ExecutionTask]
  back: []
}>()

const { t } = useI18n()
const agent = useArchAgentStore()
const taskStore = useArchTaskStore()
const requirement = useArchRequirementStore()

const picked = ref<string[]>([])
const pickerOpen = ref(false)
const created = ref(false)

onMounted(() => {
  if (props.preselect?.length) picked.value = [...props.preselect]
})

const prioColor: Record<string, string> = {
  P0: 'bg-ctp-red/15 text-ctp-red',
  P1: 'bg-ctp-peach/15 text-ctp-peach',
  P2: 'bg-ctp-overlay0/20 text-ctp-overlay1',
}
const selectedReqs = computed(() => picked.value.map((id) => requirement.byId(id)).filter((r): r is NonNullable<typeof r> => !!r))
const activeTask = computed(() => taskStore.activeTaskOf)
const busy = computed(() => agent.running)

async function start() {
  if (!picked.value.length || created.value) return
  const reqs = picked.value.map((id) => requirement.byId(id)!).filter(Boolean)
  if (!reqs.length) return
  created.value = true
  // A7：执行走 runner、对话走 tAgent，adapter 字段已无实际用途(传空占位)。
  const { exec } = await commitBatch(reqs, '')
  emit('created', exec)
}
</script>

<template>
  <div class="h-full flex flex-col min-h-0 overflow-auto">
    <div class="flex items-center gap-2 mb-3">
      <BoltIcon class="w-4 h-4 text-ctp-green" />
      <span class="text-sm font-semibold text-ctp-text">{{ t('execute.createTask') }}</span>
      <button
        class="btn btn-sm btn-ghost ml-auto"
        @click="emit('back')"
      >
        <ArrowRightIcon class="w-3.5 h-3.5 rotate-180" />{{ t('common.back') }}
      </button>
    </div>

    <!-- 互斥提示(提示性，不阻断) -->
    <div
      v-if="activeTask"
      class="mb-3 border border-ctp-peach/40 bg-ctp-peach/10 rounded-lg px-3 py-2 flex items-center gap-2 text-xs text-ctp-peach"
    >
      <ExclamationTriangleIcon class="w-4 h-4 shrink-0" />
      <span>{{ t('execute.mutexWarn', { id: activeTask.id, title: requirement.planById(activeTask.planId)?.title ?? '' }) }}</span>
    </div>

    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <SparklesIcon class="w-4 h-4 text-ctp-lavender" />{{ t('execute.createSetup') }}
        </span>
      </div>
      <div class="p-4 space-y-4">
        <div>
          <div>
            <label class="text-xs text-ctp-overlay1">{{ t('execute.selectReq') }}</label>
            <button
              class="btn btn-sm btn-blue mt-1.5"
              @click="pickerOpen = true"
            >
              <CubeIcon class="w-3.5 h-3.5" />{{ t('execute.poolPick') }} ({{ picked.length }})
            </button>
            <div
              v-if="selectedReqs.length"
              class="flex flex-wrap gap-1.5 mt-2"
            >
              <span
                v-for="r in selectedReqs"
                :key="r.id"
                class="chip bg-ctp-surface0 text-ctp-subtext1"
              >
                <span class="font-mono text-[10px] text-ctp-overlay1">{{ r.id }}</span>
                <span class="ml-1">{{ r.title }}</span>
                <span
                  class="chip !px-1 !py-0"
                  :class="prioColor[r.priority]"
                >{{ r.priority }}</span>
              </span>
            </div>
            <p
              v-else
              class="text-[11px] text-ctp-overlay1 mt-2"
            >
              {{ t('execute.planEmpty') }}
            </p>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <button
            class="btn btn-primary ml-auto"
            :disabled="!picked.length || created || busy"
            @click="start"
          >
            <RocketLaunchIcon class="w-4 h-4" />{{ created ? t('execute.created') : t('execute.start') }}
          </button>
        </div>
      </div>
    </div>

    <PoolSelectDialog
      :open="pickerOpen"
      :selected="picked"
      @update:open="(v) => (pickerOpen = v)"
      @confirm="(ids) => (picked = ids)"
    />
  </div>
</template>
