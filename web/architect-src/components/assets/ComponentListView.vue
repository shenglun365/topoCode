<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { MagnifyingGlassIcon, ArrowsRightLeftIcon, ArrowTopRightOnSquareIcon } from '@heroicons/vue/24/outline'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { kbAssetService } from '@/services/kb-assets'
import type { CodeMapping } from '@/types'

const { t } = useI18n()
const arch = useArchArchitectureStore()

const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'open-detail', id: string): void
}>()

// ---- 关键字 ----
const query = ref('')

// ---- 翻页 ----
const pageSize = 8
const page = ref(1)

/** 代码映射(后端获取；失败时为空)。 */
const codeMappings = ref<CodeMapping[]>([])
kbAssetService.codeMappings().then((m) => { codeMappings.value = m }).catch(() => { codeMappings.value = [] })

/** 同一组件包含文件(代码映射去重)。 */
const fileCount = (compId: string): number => new Set(
  codeMappings.value.filter((m) => m.targetId === compId).map((m) => m.file),
).size

/** 子组件数量。 */
const childCount = (compId: string): number => arch.components.filter((c) => c.parentId === compId).length

/** 依赖分析：下游依赖组件数。 */
const relCount = (compId: string): number => {
  const comp = arch.components.find((c) => c.id === compId)
  return comp ? comp.dependsOn.length : 0
}

const parent = (id?: string) => arch.components.find((c) => c.id === id)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  let list = arch.components
  if (q) {
    list = list.filter((c) => c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q))
  }
  return list
})

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const pageItems = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

function copy(value: string) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(value).catch(() => fallbackCopy(value))
  } else {
    fallbackCopy(value)
  }
}

function fallbackCopy(value: string) {
  const ta = document.createElement('textarea')
  ta.value = value
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try {
    document.execCommand('copy')
  } catch {
    /* ignore */
  }
  document.body.removeChild(ta)
}

function goto(p: number) {
  if (p >= 1 && p <= totalPages.value) page.value = p
}
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="panel-header">
      <span class="flex items-center gap-2">
        <ArrowsRightLeftIcon class="w-4 h-4 text-ctp-blue" />{{ t('browseList.title') }}
      </span>
      <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ filtered.length }}</span>
    </div>

    <div class="p-2 text-xs space-y-1 border-b border-ctp-surface0">
      <div class="flex items-center gap-1.5">
        <MagnifyingGlassIcon class="w-3.5 h-3.5 text-ctp-overlay0 shrink-0" />
        <input
          v-model="query"
          class="bg-ctp-crust/60 border border-ctp-surface0 rounded px-2 py-1 text-xs w-48 outline-none focus:border-ctp-blue"
          :placeholder="t('browseList.search')"
        >
      </div>
    </div>

    <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead>
          <tr class="text-left border-b border-ctp-surface0 text-ctp-overlay1">
            <th class="px-3 py-2 font-medium whitespace-nowrap">
              {{ t('browseList.name') }}
            </th>
            <th class="px-3 py-2 font-medium whitespace-nowrap">
              {{ t('browseList.id') }}
            </th>
            <th class="px-3 py-2 font-medium whitespace-nowrap">
              {{ t('browseList.relType') }}
            </th>
            <th class="px-3 py-2 font-medium whitespace-nowrap">
              {{ t('browseList.parentName') }}
            </th>
            <th class="px-3 py-2 font-medium whitespace-nowrap">
              {{ t('browseList.parentId') }}
            </th>
            <th class="px-3 py-2 font-medium whitespace-nowrap">
              {{ t('browseList.childCount') }}
            </th>
            <th class="px-3 py-2 font-medium whitespace-nowrap">
              {{ t('browseList.fileCount') }}
            </th>
            <th class="px-3 py-2 font-medium whitespace-nowrap">
              {{ t('browseList.detail') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in pageItems"
            :key="c.id"
            class="border-b border-ctp-surface0 last:border-0 hover:bg-ctp-surface0/50 cursor-pointer"
            @click="emit('select', c.id)"
          >
            <td class="px-3 py-2">
              <div class="flex items-center gap-1.5 text-ctp-text font-medium">
                {{ c.name }}
                <button
                  class="text-ctp-overlay1 hover:text-ctp-sky p-0.5"
                  :title="t('browseList.copy')"
                  @click.stop="copy(c.name)"
                >
                  <svg
                    class="w-3 h-3"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  ><path d="M8 8h12v12H8zM4 16V4h12" /></svg>
                </button>
                <span
                  class="chip"
                  :class="{
                    'bg-ctp-sky/15 text-ctp-sky': c.kind === 'gateway',
                    'bg-ctp-blue/15 text-ctp-blue': c.kind === 'service',
                    'bg-ctp-teal/15 text-ctp-teal': c.kind === 'infra',
                    'bg-ctp-mauve/15 text-ctp-mauve': c.kind === 'storage',
                    'bg-ctp-peach/15 text-ctp-peach': c.kind === 'integration',
                  }"
                >{{ t(`architecture.kind.${c.kind}`) }}</span>
              </div>
            </td>
            <td class="px-3 py-2">
              <button
                class="font-mono text-ctp-subtext1 hover:text-ctp-blue"
                :title="t('browseList.copy')"
                @click.stop="copy(c.id)"
              >
                {{ c.id }}
              </button>
            </td>
            <td class="px-3 py-2">
              <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ relCount(c.id) }}</span>
              <span class="text-[10px] text-ctp-overlay1">
                {{ t('kbQuery.depends') }}
              </span>
            </td>
            <td class="px-3 py-2">
              <div v-if="parent(c.parentId)">
                <div class="flex items-center gap-1.5 text-ctp-text">
                  {{ parent(c.parentId)!.name }}
                  <button
                    class="text-ctp-overlay1 hover:text-ctp-sky p-0.5"
                    :title="t('browseList.copy')"
                    @click.stop="copy(parent(c.parentId)!.name)"
                  >
                    <svg
                      class="w-3 h-3"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                    ><path d="M8 8h12v12H8zM4 16V4h12" /></svg>
                  </button>
                </div>
              </div>
              <span
                v-else
                class="text-ctp-overlay1"
              >—</span>
            </td>
            <td class="px-3 py-2">
              <button
                v-if="parent(c.parentId)"
                class="font-mono text-ctp-subtext1 hover:text-ctp-blue"
                :title="t('browseList.copy')"
                @click.stop="copy(parent(c.parentId)!.id)"
              >
                {{ parent(c.parentId)!.id }}
              </button>
              <span
                v-else
                class="text-ctp-overlay1"
              >—</span>
            </td>
            <td class="px-3 py-2 text-ctp-subtext0">
              {{ childCount(c.id) }}
            </td>
            <td class="px-3 py-2 text-ctp-subtext0">
              {{ fileCount(c.id) }}
            </td>
            <td class="px-3 py-2">
              <button
                class="flex items-center gap-1 text-ctp-blue hover:underline"
                @click.stop="emit('open-detail', c.id)"
              >
                <ArrowTopRightOnSquareIcon class="w-3.5 h-3.5" />{{ t('browseList.view') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="!filtered.length"
      class="p-4 text-center text-[11px] text-ctp-overlay1"
    >
      {{ t('browseList.empty') }}
    </div>

    <!-- 翻页 -->
    <div
      v-else
      class="flex items-center justify-between px-3 py-2 border-t border-ctp-surface0"
    >
      <span class="text-[11px] text-ctp-overlay1">{{ page }} / {{ totalPages }}</span>
      <div class="flex items-center gap-1">
        <button
          class="btn btn-sm"
          :disabled="page === 1"
          @click="goto(page - 1)"
        >
          {{ t('browseList.prev') }}
        </button>
        <button
          class="btn btn-sm"
          :disabled="page === totalPages"
          @click="goto(page + 1)"
        >
          {{ t('browseList.next') }}
        </button>
      </div>
    </div>
  </div>
</template>