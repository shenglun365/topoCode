<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSplitPane } from '@/composables/useSplitPane'
import { useArchUnitTestStore } from '@/stores/unit-test-store'
import UnitTestListPanel from './UnitTestListPanel.vue'
import UnitTestSessionPanel from './UnitTestSessionPanel.vue'
import { ArrowLeftIcon } from '@heroicons/vue/24/outline'

const props = defineProps<{ sessionId: string }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const store = useArchUnitTestStore()

const session = computed(() => store.sessions.find((s) => s.id === props.sessionId))
const { splitPct, dragging, boxRef, onDown, onMove, onUp } = useSplitPane({ max: 62, min: 42 })
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="shrink-0 flex items-center gap-2 pb-3">
      <button
        class="btn btn-sm btn-ghost"
        @click="emit('close')"
      >
        <ArrowLeftIcon class="w-3.5 h-3.5" />{{ t('common.back') }}
      </button>
      <span class="chip bg-ctp-lavender/15 text-ctp-lavender font-mono text-[10px] shrink-0">{{ session?.id }}</span>
      <span class="text-sm font-semibold text-ctp-text truncate">{{ session?.title }}</span>
    </div>

    <div
      ref="boxRef"
      class="flex-1 min-h-0 flex"
    >
      <!-- 左栏：单测列表 -->
      <div
        class="min-h-0 overflow-hidden pr-1"
        :style="{ width: splitPct + '%' }"
      >
        <UnitTestListPanel :session-id="session!.id" />
      </div>

      <!-- 分割线 -->
      <div
        class="w-4 shrink-0 -mx-0.5 flex items-center justify-center cursor-col-resize select-none touch-none group"
        @pointerdown="onDown"
        @pointermove="onMove"
        @pointerup="onUp"
        @pointercancel="onUp"
        @pointerleave="onUp"
      >
        <div
          class="h-12 w-0.5 rounded-full bg-ctp-overlay1/40 transition-colors group-hover:bg-ctp-blue/60"
          :class="dragging ? '!bg-ctp-blue/70' : ''"
        />
      </div>

      <!-- 右栏：执行反馈 -->
      <div class="min-h-0 flex-1 flex flex-col">
        <UnitTestSessionPanel v-if="session" :session="session" />
      </div>
    </div>
  </div>
</template>