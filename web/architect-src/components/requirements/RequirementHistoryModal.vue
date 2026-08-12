<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ClipboardDocumentListIcon, XMarkIcon, ArrowDownTrayIcon, TrashIcon, CheckIcon } from '@heroicons/vue/24/outline'
import type { ConversationDetail, ConversationSummary } from '@/types'
import { requirementService } from '@/services/requirement-service'

const props = defineProps<{ open: boolean; activeConvId?: string; kind?: string }>()
const emit = defineEmits<{ close: []; import: [conv: ConversationDetail] }>()

const { t } = useI18n()

const loading = ref(false)
const items = ref<ConversationSummary[]>([])
const loadingDetail = ref(false)

/** 会话归类(requirement | asset | ...)：决定列表与文案。 */
const kind = () => props.kind ?? 'requirement'
const isAsset = () => kind() === 'asset'

const labels = computed(() => {
  if (isAsset()) {
    return {
      title: t('assetMgmt.history.title'),
      hint: t('assetMgmt.history.hint'),
      empty: t('assetMgmt.history.empty'),
      import: t('assetMgmt.history.import'),
      imported: t('assetMgmt.history.imported'),
      delete: t('assetMgmt.history.delete'),
      loading: t('assetMgmt.history.loading'),
    }
  }
  return {
    title: t('requirement.history.title'),
    hint: t('requirement.history.hint'),
    empty: t('requirement.history.empty'),
    import: t('requirement.history.import'),
    imported: t('requirement.history.imported'),
    delete: t('requirement.history.delete'),
    loading: t('requirement.history.loading'),
  }
})

async function load() {
  if (!props.open) return
  loading.value = true
  try {
    items.value = await requirementService.conversations(kind())
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (v) => {
    if (v) load()
  },
)

async function onImport(item: ConversationSummary) {
  if (loadingDetail.value) return
  loadingDetail.value = true
  try {
    const detail = await requirementService.conversation(item.id)
    emit('import', detail)
  } finally {
    loadingDetail.value = false
  }
}

async function onDelete(item: ConversationSummary) {
  if (loadingDetail.value) return
  loadingDetail.value = true
  try {
    await requirementService.deleteConversation(item.id)
    await load()
  } finally {
    loadingDetail.value = false
  }
}

function fmtTime(ts?: number): string {
  if (!ts) return ''
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="panel w-full max-w-lg max-h-[70vh] overflow-hidden flex flex-col">
      <div class="panel-header shrink-0">
        <span class="flex items-center gap-2">
          <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-blue" />{{ labels.title }}
        </span>
        <button
          class="btn btn-xs btn-ghost"
          @click="emit('close')"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>

      <div class="flex-1 min-h-0 p-3 flex flex-col gap-2">
        <p class="text-[11px] text-ctp-subtext0">
          {{ labels.hint }}
        </p>

        <div
          v-if="loading"
          class="text-xs text-ctp-overlay1"
        >
          {{ labels.loading }}
        </div>

        <div
          v-else-if="!items.length"
          class="text-xs text-ctp-overlay1 text-center py-8 border border-dashed border-ctp-surface0 rounded-lg"
        >
          {{ labels.empty }}
        </div>

        <div
          v-else
          class="min-h-0 overflow-auto space-y-2"
        >
          <div
            v-for="item in items"
            :key="item.id"
            class="border rounded-lg p-2.5 flex items-start gap-2 transition-colors"
            :class="item.id === props.activeConvId
              ? 'border-ctp-green/40 bg-ctp-green/10 ring-1 ring-ctp-green/40'
              : 'border-ctp-surface0 hover:border-ctp-overlay1/50'"
          >
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-xs font-semibold text-ctp-text truncate">{{ item.title }}</span>
                <span class="chip bg-ctp-surface0 text-[10px] shrink-0">{{ item.msgCount }} msg</span>
                <span
                  v-if="item.updatedAt"
                  class="text-[10px] text-ctp-overlay1 shrink-0"
                >{{ fmtTime(item.updatedAt) }}</span>
              </div>
              <p class="mt-1 text-[11px] text-ctp-subtext1 line-clamp-2 whitespace-pre-wrap">
                {{ item.preview || '—' }}
              </p>
            </div>
            <div class="flex items-center gap-1 shrink-0">
              <span
                v-if="item.id === props.activeConvId"
                class="chip bg-ctp-green/20 text-ctp-green text-[10px] shrink-0"
              >
                <CheckIcon class="w-3 h-3 inline" />{{ labels.imported }}
              </span>
              <button
                v-else
                class="btn btn-sm btn-green !py-1"
                :disabled="loadingDetail"
                @click="onImport(item)"
              >
                <ArrowDownTrayIcon class="w-3 h-3" />{{ labels.import }}
              </button>
              <button
                class="btn btn-sm btn-ghost !py-1 text-ctp-red"
                :disabled="loadingDetail"
                :title="labels.delete"
                @click="onDelete(item)"
              >
                <TrashIcon class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
