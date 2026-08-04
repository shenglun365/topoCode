<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CubeIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import type { AssetDetail } from '@/types'
import { kbAssetService } from '@/services/kb-assets'

const props = defineProps<{ open: boolean; scopedIds: string[] }>()
const emit = defineEmits<{ close: []; add: [assetId: string] }>()

const { t } = useI18n()

const pickQuery = ref('')
const pickLoading = ref(false)
const pickResults = ref<AssetDetail[]>([])
const isScoped = (id: string) => props.scopedIds.includes(id)

watch(
  () => props.open,
  async (v) => {
    if (!v) return
    pickLoading.value = true
    pickQuery.value = ''
    pickResults.value = await kbAssetService.searchComponents('')
    pickLoading.value = false
  },
)

watch(pickQuery, async (q) => {
  if (!props.open) return
  pickLoading.value = true
  pickResults.value = await kbAssetService.searchComponents(q)
  pickLoading.value = false
})

function addComponent(assetId: string) {
  if (isScoped(assetId)) return
  emit('add', assetId)
  emit('close')
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="panel w-full max-w-md max-h-[70vh] overflow-hidden flex flex-col">
      <div class="panel-header shrink-0">
        <span class="flex items-center gap-2">
          <CubeIcon class="w-4 h-4 text-ctp-blue" />{{ t('requirement.form.assetPickTitle') }}
        </span>
        <button
          class="btn btn-xs btn-ghost"
          @click="emit('close')"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      <div class="p-3 flex flex-col gap-2 min-h-0 flex-1">
        <input
          v-model="pickQuery"
          class="input"
          :placeholder="t('requirement.form.assetPickSearch')"
        >
        <p
          v-if="pickLoading"
          class="text-xs text-ctp-overlay1"
        >
          {{ t('requirement.form.assetPickLoading') }}
        </p>
        <div
          v-else
          class="min-h-0 overflow-auto space-y-1"
        >
          <p
            v-if="!pickResults.length"
            class="text-xs text-ctp-overlay1 text-center py-6"
          >
            {{ t('requirement.form.assetPickEmpty') }}
          </p>
          <button
            v-for="r in pickResults"
            :key="r.assetId"
            class="w-full flex items-center gap-2 rounded-lg border border-ctp-surface0 px-2 py-1.5 text-left transition-colors"
            :class="isScoped(r.assetId) ? 'opacity-50 cursor-default' : 'hover:bg-ctp-surface0/60 cursor-pointer'"
            :disabled="isScoped(r.assetId)"
            @click="addComponent(r.assetId)"
          >
            <CubeIcon class="w-3.5 h-3.5 text-ctp-blue shrink-0" />
            <span class="text-xs font-medium text-ctp-text truncate">{{ r.name }}</span>
            <span class="chip bg-ctp-surface0 text-[10px] shrink-0">{{ t(`architecture.kind.${r.kind ?? 'service'}`) }}</span>
            <span
              v-if="r.file"
              class="text-[10px] font-mono text-ctp-overlay1 truncate shrink-0 max-w-[8rem]"
            >{{ r.file }}</span>
            <span
              v-if="isScoped(r.assetId)"
              class="ml-auto text-[10px] text-ctp-green shrink-0"
            >{{ t('requirement.form.assetPickAdded') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
