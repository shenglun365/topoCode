<script setup lang="ts">
/**
 * 提取范围确认弹窗（交互提取闭环）：按目录分组列出提取范围文件，
 * 用户可取消勾选缩小分析范围；确认后由调用方生成任务开始提取。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { FolderIcon, DocumentIcon } from '@heroicons/vue/24/outline'

const props = defineProps<{
  open: boolean
  title: string
  files: string[]
  busy?: boolean
  /** 显示「全量更新」选项(清除全库+全量重提，忽略文件选择)；仅对比闭环入口传入。 */
  showFull?: boolean
}>()
const emit = defineEmits<{
  (e: 'confirm', files: string[], opts: { impl: boolean; logic: boolean; full: boolean }): void
  (e: 'close'): void
}>()

const { t } = useI18n()

/** 目录 → 文件[]（保持组内路径排序）。 */
const groups = computed(() => {
  const m = new Map<string, string[]>()
  for (const f of [...props.files].sort()) {
    const i = f.lastIndexOf('/')
    const dir = i > 0 ? f.slice(0, i) : '.'
    if (!m.has(dir)) m.set(dir, [])
    m.get(dir)!.push(f)
  }
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
})

const selected = ref<Set<string>>(new Set())
watch(() => [props.open, props.files] as const, ([o]) => {
  if (o) {
    selected.value = new Set(props.files)
    implSel.value = true
    logicSel.value = true
    fullSel.value = false
  }
})

// ---- 提取粒度：逻辑层基于实现层归纳——勾逻辑时实现强制勾选且不可取消 ----
const implSel = ref(true)
const logicSel = ref(true)
const fullSel = ref(false)
watch(logicSel, (v) => {
  if (v) implSel.value = true
})
const canConfirm = computed(() => (implSel.value || logicSel.value) && (fullSel.value || selected.value.size > 0))

function doConfirm() {
  emit('confirm', [...selected.value], { impl: implSel.value, logic: logicSel.value, full: fullSel.value })
}

const selCount = computed(() => selected.value.size)
const allSelected = computed(() => props.files.length > 0 && selected.value.size === props.files.length)

function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(props.files)
}
function toggleDir(dir: string, files: string[]) {
  const allIn = files.every((f) => selected.value.has(f))
  const next = new Set(selected.value)
  for (const f of files) {
    if (allIn) next.delete(f)
    else next.add(f)
  }
  selected.value = next
}
function dirAllIn(files: string[]): boolean {
  return files.every((f) => selected.value.has(f))
}
function dirSomeIn(files: string[]): boolean {
  return !dirAllIn(files) && files.some((f) => selected.value.has(f))
}
function toggleFile(f: string) {
  const next = new Set(selected.value)
  if (next.has(f)) next.delete(f)
  else next.add(f)
  selected.value = next
}
function fileBase(f: string): string {
  const i = f.lastIndexOf('/')
  return i > 0 ? f.slice(i + 1) : f
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[240] flex items-center justify-center bg-black/45 p-4" @click.self="emit('close')">
      <div class="flex max-h-[80vh] w-[32rem] max-w-full flex-col rounded-xl border border-ctp-surface0 bg-ctp-mantle p-4 shadow-2xl">
        <p class="text-sm font-semibold text-ctp-text">{{ title }}</p>
        <p class="mt-1 text-[11px] leading-relaxed text-ctp-overlay1">
          {{ t('assetMgmt.scopeModal.hint', { n: files.length }) }}
        </p>
        <!-- 提取粒度：逻辑层基于实现层归纳，勾逻辑时实现强制勾选 -->
        <div class="mt-2 flex items-center gap-4 text-[11px]">
          <span class="text-ctp-overlay1">{{ t('assetMgmt.scopeModal.levels') }}</span>
          <label class="flex cursor-pointer items-center gap-1.5 text-ctp-subtext1">
            <input v-model="implSel" type="checkbox" class="accent-ctp-blue" :disabled="logicSel">
            {{ t('assetMgmt.scopeModal.levelImpl') }}
          </label>
          <label class="flex cursor-pointer items-center gap-1.5 text-ctp-subtext1" :title="t('assetMgmt.scopeModal.levelLogicTip')">
            <input v-model="logicSel" type="checkbox" class="accent-ctp-blue">
            {{ t('assetMgmt.scopeModal.levelLogic') }}
          </label>
        </div>
        <!-- 清除重建警示(提取即替换语义，恒示) -->
        <div class="mt-2 rounded-md border border-ctp-peach/40 bg-ctp-peach/10 px-2.5 py-1.5 text-[11px] leading-relaxed text-ctp-peach">
          {{ fullSel ? t('assetMgmt.scopeModal.fullWarn') : t('assetMgmt.scopeModal.clearWarn') }}
        </div>
        <label v-if="showFull" class="mt-2 flex cursor-pointer items-center gap-1.5 text-[11px] text-ctp-subtext1">
          <input v-model="fullSel" type="checkbox" class="accent-ctp-red">
          <span class="font-medium text-ctp-red">{{ t('assetMgmt.scopeModal.fullUpdate') }}</span>
          <span class="text-ctp-overlay0">{{ t('assetMgmt.scopeModal.fullUpdateHint') }}</span>
        </label>
        <div v-if="!fullSel" class="mt-2 flex items-center gap-2 text-[11px]">
          <label class="flex cursor-pointer items-center gap-1.5 text-ctp-subtext1">
            <input type="checkbox" class="accent-ctp-blue" :checked="allSelected" @change="toggleAll">
            {{ t('assetMgmt.scopeModal.all') }}
          </label>
          <span class="flex-1" />
          <span class="text-ctp-overlay1">{{ t('assetMgmt.scopeModal.selected', { n: selCount }) }}</span>
        </div>
        <div
          v-if="fullSel"
          class="mt-2 min-h-0 flex-1 overflow-y-auto rounded-md border border-ctp-surface0 bg-ctp-crust/60 p-3 text-[11px] leading-relaxed text-ctp-overlay1"
        >
          {{ t('assetMgmt.scopeModal.fullFilesHint', { n: files.length }) }}
        </div>
        <div v-else class="mt-2 min-h-0 flex-1 overflow-y-auto rounded-md border border-ctp-surface0 bg-ctp-crust/60 p-2">
          <div v-for="[dir, fs] in groups" :key="dir" class="mb-2">
            <label class="flex cursor-pointer items-center gap-1.5 rounded px-0.5 py-0.5 text-[11px] text-ctp-subtext1 hover:bg-ctp-surface0/60">
              <input
                type="checkbox" class="accent-ctp-blue"
                :checked="dirAllIn(fs)"
                :indeterminate="dirSomeIn(fs)"
                @change="toggleDir(dir, fs)"
              >
              <FolderIcon class="h-3.5 w-3.5 text-ctp-yellow/80" />
              <span class="font-mono">{{ dir === '.' ? '.' : `${dir}/` }}</span>
              <span class="text-ctp-overlay0">{{ fs.length }}</span>
            </label>
            <div class="ml-5 space-y-0.5">
              <label
                v-for="f in fs" :key="f"
                class="flex cursor-pointer items-center gap-1.5 rounded px-0.5 py-0.5 text-[10px] hover:bg-ctp-surface0/40"
                :title="f"
              >
                <input
                  type="checkbox" class="accent-ctp-blue"
                  :checked="selected.has(f)"
                  @change="toggleFile(f)"
                >
                <DocumentIcon class="h-3 w-3 shrink-0 text-ctp-overlay0" />
                <span class="truncate font-mono text-ctp-subtext0">{{ fileBase(f) }}</span>
              </label>
            </div>
          </div>
        </div>
        <div class="mt-3 flex justify-end gap-2">
          <button class="btn btn-ghost text-xs" :disabled="busy" @click="emit('close')">{{ t('common.cancel') }}</button>
          <button
            class="btn text-xs"
            :class="fullSel ? 'btn-error' : 'btn-blue'"
            :disabled="busy || !canConfirm"
            @click="doConfirm"
          >{{ fullSel ? t('assetMgmt.scopeModal.confirmFull') : t('assetMgmt.scopeModal.confirm', { n: selCount }) }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
