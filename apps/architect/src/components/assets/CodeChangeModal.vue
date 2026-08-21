<script setup lang="ts">
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import type { CodeChangeItem } from '@/services/arch-change-service'

defineProps<{
  item: CodeChangeItem | null
  title?: string
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { t } = useI18n()

function changeCls(c: string): string {
  return c === 'added' ? 'bg-ctp-green/15 text-ctp-green'
    : c === 'removed' ? 'bg-ctp-red/15 text-ctp-red'
      : c === 'modified' ? 'bg-ctp-peach/15 text-ctp-peach'
        : 'bg-ctp-surface0 text-ctp-subtext0'
}
</script>

<template>
  <div
    v-if="item"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="w-full max-w-2xl max-h-[85vh] flex flex-col bg-ctp-mantle border border-ctp-surface0 rounded-xl overflow-hidden shadow-xl">
      <div class="flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0">
        <span
          class="chip shrink-0"
          :class="changeCls(item.change)"
        >{{ t(`architecture.change.${item.change}`) }}</span>
        <span class="flex-1 truncate text-sm font-medium text-ctp-text">{{ item.title }}</span>
        <button
          class="text-ctp-overlay1 hover:text-ctp-text p-1 cursor-pointer"
          @click="emit('close')"
        >
          <XMarkIcon class="w-5 h-5" />
        </button>
      </div>

      <div class="px-4 py-2 border-b border-ctp-surface0 text-[11px] text-ctp-subtext0 flex items-center gap-2">
        <span class="chip bg-ctp-surface0 text-ctp-sapphire font-mono truncate">{{ item.file }}</span>
        <span class="truncate">{{ item.summary }}</span>
      </div>

      <div class="flex-1 overflow-auto p-4 grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div class="min-w-0">
          <div class="text-[11px] font-medium text-ctp-overlay1 mb-1">
            {{ t('archChange.before') }}
          </div>
          <pre class="bg-ctp-crust border border-ctp-surface0 rounded-md p-3 text-[11px] leading-relaxed text-ctp-subtext1 overflow-auto max-h-72 whitespace-pre">{{ item.before.length ? item.before.join('\n') : '—' }}</pre>
        </div>
        <div class="min-w-0">
          <div class="text-[11px] font-medium text-ctp-overlay1 mb-1">
            {{ t('archChange.after') }}
          </div>
          <pre class="bg-ctp-crust border border-ctp-green/20 rounded-md p-3 text-[11px] leading-relaxed text-ctp-subtext1 overflow-auto max-h-72 whitespace-pre">{{ item.after.length ? item.after.join('\n') : '—' }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
