<script setup lang="ts">
/**
 * 新建逻辑视图（模式 2）：手动选择核心实现资产（种子节点，非分析范围），
 * 提交后 analyze 作业沿调用依赖拓展成员全集 + LLM 概括（任务中心可见进度）。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { BeakerIcon, MagnifyingGlassIcon } from '@heroicons/vue/24/outline'
import { kindChipClass } from '@/services/semantic-kind-style'
import { useAssetWorkspaceCtx } from '..'
import type { SemanticAsset } from '@/types'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const { t } = useI18n()
const { items, createLogicView } = useAssetWorkspaceCtx()

const name = ref('')
const q = ref('')
const expand = ref<'core' | '1' | '2' | 'all'>('all')
const selected = ref<Set<string>>(new Set())
const submitting = ref(false)

watch(() => props.open, (o) => {
  if (o) {
    name.value = ''
    q.value = ''
    expand.value = 'all'
    selected.value = new Set()
  }
})

/** 搜索+未删除的实现资产(按名称/符号/文件)。 */
const candidates = computed<SemanticAsset[]>(() => {
  const kw = q.value.trim().toLowerCase()
  const list = (items.value as SemanticAsset[]).filter((a) => a.status !== 'deleted')
  if (!kw) return list.slice(0, 200)
  return list.filter((a) =>
    a.name.toLowerCase().includes(kw)
    || (a.astRefs?.[0]?.file || '').toLowerCase().includes(kw)
    || (a.astRefs?.[0]?.symbol || '').toLowerCase().includes(kw)).slice(0, 200)
})

function toggle(id: string) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

async function submit() {
  if (submitting.value) return
  if (!name.value.trim() || !selected.value.size) return
  submitting.value = true
  try {
    await createLogicView({ name: name.value.trim(), coreIds: [...selected.value], expand: expand.value })
    emit('close')
  } catch (e) {
    console.warn('[logic-view] create failed:', e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[240] flex items-center justify-center bg-black/45 p-4" @click.self="emit('close')">
      <div class="flex max-h-[80vh] w-[34rem] max-w-full flex-col rounded-xl border border-ctp-surface0 bg-ctp-mantle p-4 shadow-2xl">
        <p class="flex items-center gap-1.5 text-sm font-semibold text-ctp-text">
          <BeakerIcon class="w-4 h-4 text-ctp-mauve" />{{ t('assetMgmt.logicViews.createTitle') }}
        </p>
        <p class="mt-1 text-[11px] leading-relaxed text-ctp-overlay1">
          {{ t('assetMgmt.logicViews.createHintBody') }}
        </p>
        <div class="mt-2 flex items-center gap-2">
          <input
            v-model="name"
            class="input flex-1 !py-1 !text-xs"
            :placeholder="t('assetMgmt.logicViews.namePlaceholder')"
          >
          <select v-model="expand" class="input !py-1 !px-2 !text-[11px] w-auto shrink-0" :title="t('assetMgmt.logicViews.expandHint')">
            <option value="all">{{ t('assetMgmt.logicViews.expandAll') }}</option>
            <option value="1">{{ t('assetMgmt.logicViews.expand1') }}</option>
            <option value="2">{{ t('assetMgmt.logicViews.expand2') }}</option>
            <option value="core">{{ t('assetMgmt.logicViews.expandCore') }}</option>
          </select>
        </div>
        <div class="mt-2 flex items-center gap-1.5 rounded-md border border-ctp-surface0 bg-ctp-crust/60 px-2 py-1">
          <MagnifyingGlassIcon class="w-3.5 h-3.5 text-ctp-overlay0 shrink-0" />
          <input v-model="q" class="w-full bg-transparent text-[11px] text-ctp-subtext1 outline-none" :placeholder="t('assetMgmt.logicViews.searchPlaceholder')">
          <span class="text-[10px] text-ctp-overlay0 shrink-0">{{ t('assetMgmt.logicViews.selectedN', { n: selected.size }) }}</span>
        </div>
        <div class="mt-2 min-h-0 flex-1 overflow-y-auto rounded-md border border-ctp-surface0 bg-ctp-crust/60 p-2">
          <label
            v-for="a in candidates"
            :key="a.id"
            class="flex cursor-pointer items-center gap-1.5 rounded px-0.5 py-0.5 text-[10px] hover:bg-ctp-surface0/40"
            :title="a.astRefs?.[0]?.file"
          >
            <input type="checkbox" class="accent-ctp-mauve" :checked="selected.has(a.id)" @change="toggle(a.id)">
            <span class="chip !text-[8px] shrink-0" :class="kindChipClass(a.kind)">{{ t(`assetMgmt.kind.${a.kind}`) }}</span>
            <span class="truncate text-ctp-subtext1">{{ a.name }}</span>
            <span class="truncate font-mono text-ctp-overlay0">{{ a.astRefs?.[0]?.file }}</span>
          </label>
        </div>
        <div class="mt-3 flex justify-end gap-2">
          <button class="btn btn-ghost text-xs" :disabled="submitting" @click="emit('close')">{{ t('common.cancel') }}</button>
          <button
            class="btn btn-blue text-xs"
            :disabled="submitting || !name.trim() || !selected.size"
            @click="submit"
          >{{ t('assetMgmt.logicViews.createSubmit') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
