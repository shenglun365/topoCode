<template>
  <!-- 图谱范围逻辑解析浮窗：≤30 节点一步确认；>30 先提纲(核心×跳数档勾选)再解析。
       解析走 induce-scope 作业(任务中心排队可见)，完成后回执新视图 id 列表。 -->
  <div class="fixed z-40 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[34rem] max-h-[80%] flex flex-col rounded-lg border border-ctp-surface1 bg-ctp-mantle shadow-2xl">
    <header class="flex items-center gap-2 px-3 py-2 border-b border-ctp-surface1 shrink-0">
      <SparklesIcon class="w-4 h-4 text-ctp-mauve shrink-0" />
      <span class="text-xs font-semibold text-ctp-text">{{ t('assetMgmt.logicViews.scopeTitle') }}</span>
      <span class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.logicViews.scopeNodes', { n: nodes.length }) }}</span>
      <button class="ml-auto text-ctp-overlay0 hover:text-ctp-text shrink-0" :title="t('common.close')" @click="emit('close')">
        <XMarkIcon class="w-4 h-4" />
      </button>
    </header>

    <div class="overflow-y-auto px-3 py-2.5 space-y-3 text-xs">
      <!-- 阶段①：小范围一步确认 -->
      <template v-if="stage === 'confirm'">
        <p class="text-ctp-subtext1 leading-relaxed">{{ t('assetMgmt.logicViews.scopeDirectHint') }}</p>
        <div class="flex flex-wrap gap-1">
          <span v-for="n in nodes.slice(0, 24)" :key="n.id" class="px-1.5 py-0.5 rounded border border-ctp-surface1 text-ctp-subtext1 text-[11px]">{{ n.name }}</span>
          <span v-if="nodes.length > 24" class="text-ctp-overlay0 self-center">+{{ nodes.length - 24 }}</span>
        </div>
      </template>

      <!-- 阶段②：提纲(跳数档 + 核心组勾选) -->
      <template v-else-if="stage === 'outline'">
        <div class="flex items-center gap-2">
          <span class="text-ctp-overlay1 shrink-0">{{ t('assetMgmt.logicViews.hopsLabel') }}</span>
          <button
            v-for="h in ([1, 2, 3] as const)" :key="h"
            class="px-2 py-0.5 rounded border text-[11px] transition-colors"
            :class="hops === h ? 'border-ctp-mauve/60 bg-ctp-mauve/20 text-ctp-mauve' : 'border-ctp-surface1 text-ctp-subtext1 hover:text-ctp-text'"
            @click="hops = h"
          >{{ t('assetMgmt.logicViews.hopsN', { n: h }) }}</button>
          <span class="ml-auto text-[10px] text-ctp-overlay0">{{ t('assetMgmt.logicViews.hopsHint') }}</span>
        </div>
        <div v-if="outlineLoading" class="flex items-center gap-1.5 text-ctp-overlay0">
          <ArrowPathIcon class="w-3.5 h-3.5 animate-spin" />{{ t('assetMgmt.logicViews.outlineLoading') }}
        </div>
        <template v-else>
          <label
            v-for="c in cores" :key="c.coreId"
            class="flex items-center gap-2 px-2 py-1.5 rounded border cursor-pointer transition-colors"
            :class="checked.has(c.coreId) ? 'border-ctp-mauve/40 bg-ctp-mauve/8' : 'border-ctp-surface1 hover:border-ctp-overlay0'"
          >
            <input type="checkbox" class="accent-ctp-mauve" :checked="checked.has(c.coreId)" @change="toggle(c.coreId)" />
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <span class="truncate text-ctp-text font-medium">{{ c.coreName }}</span>
                <span v-if="c.coreId === selId" class="chip !text-[8px] bg-ctp-blue/15 text-ctp-blue shrink-0">{{ t('assetMgmt.logicViews.scopeSelNode') }}</span>
              </div>
              <div class="text-[10px] text-ctp-overlay0">
                {{ t('assetMgmt.logicViews.coreDegree', { n: c.degree }) }} ·
                {{ t('assetMgmt.logicViews.hopsMembers', { h: hops, n: (c.hops[String(hops)] || []).length }) }}
              </div>
            </div>
          </label>
          <p v-if="!cores.length" class="text-ctp-overlay0">{{ t('assetMgmt.logicViews.outlineEmpty') }}</p>
        </template>
      </template>

      <!-- 阶段③：解析中(作业排队·任务中心可见) -->
      <template v-else-if="stage === 'submitting'">
        <div class="flex items-center gap-2 py-4 justify-center text-ctp-subtext1">
          <ArrowPathIcon class="w-4 h-4 animate-spin text-ctp-mauve" />
          {{ t('assetMgmt.logicViews.scopeSubmitting') }}
        </div>
        <p class="text-[11px] text-ctp-overlay0 text-center">{{ t('assetMgmt.logicViews.scopeQueueHint') }}</p>
      </template>
    </div>

    <footer v-if="stage !== 'submitting'" class="flex items-center gap-2 px-3 py-2 border-t border-ctp-surface1 shrink-0">
      <span class="text-[10px] text-ctp-overlay0">{{ footerHint }}</span>
      <button class="ml-auto btn-secondary text-xs" @click="emit('close')">{{ t('common.cancel') }}</button>
      <button
        class="btn-primary text-xs flex items-center gap-1"
        :disabled="!canSubmit"
        @click="submit"
      >
        <SparklesIcon class="w-3.5 h-3.5" />
        {{ stage === 'confirm' ? t('assetMgmt.logicViews.scopeSubmitDirect') : t('assetMgmt.logicViews.scopeSubmit') }}
      </button>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, SparklesIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { semanticAssetService } from '@/services/semantic-asset-service'

const props = defineProps<{ nodes: { id: string; name: string }[]; selId?: string }>()
const emit = defineEmits<{ close: []; done: [viewIds: string[]] }>()
const { t } = useI18n()

const DIRECT_LIMIT = 30
const stage = ref<'confirm' | 'outline' | 'submitting' | 'done'>('confirm')
const hops = ref<1 | 2 | 3>(1)
const cores = ref<{ coreId: string; coreName: string; degree: number; hops: Record<'1' | '2' | '3', string[]> }[]>([])
const outlineLoading = ref(false)
const checked = ref(new Set<string>())
const submitError = ref('')

const canSubmit = computed(() =>
  stage.value === 'confirm' ? props.nodes.length > 0
    : stage.value === 'outline' ? checked.value.size > 0 : false)
const footerHint = computed(() => {
  if (stage.value === 'confirm') return t('assetMgmt.logicViews.scopeDirectCount', { n: props.nodes.length })
  if (stage.value === 'outline') {
    const total = cores.value.filter((c) => checked.value.has(c.coreId))
      .reduce((n, c) => n + new Set(c.hops[String(hops.value)] || []).size, 0)
    return t('assetMgmt.logicViews.scopeSelected', { groups: checked.value.size, n: total })
  }
  return ''
})

function toggle(id: string) {
  const s = new Set(checked.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  checked.value = s
}

async function submit() {
  if (stage.value === 'confirm') {
    const core = props.selId && props.nodes.some((n) => n.id === props.selId)
      ? props.selId : (props.nodes[0]?.id ?? '')
    await run([{ coreId: core, hops: 1, memberIds: props.nodes.map((n) => n.id) }])
    return
  }
  const groups = cores.value.filter((c) => checked.value.has(c.coreId))
    .map((c) => ({ coreId: c.coreId, hops: hops.value as number, memberIds: [...new Set(c.hops[String(hops.value)] || [])] as string[] }))
    .filter((g) => g.memberIds.length)
  if (!groups.length) return
  await run(groups)
}

async function run(groups: { coreId: string; hops: number; memberIds: string[] }[]) {
  stage.value = 'submitting'
  submitError.value = ''
  try {
    const r = await semanticAssetService.induceScope(groups)
    stage.value = 'done'
    emit('done', r?.viewIds ?? [])
  } catch (e: unknown) {
    submitError.value = (e as { message?: string })?.message || 'failed'
    stage.value = 'outline'
  }
}

onMounted(async () => {
  if (props.nodes.length <= DIRECT_LIMIT) return
  stage.value = 'outline'
  outlineLoading.value = true
  try {
    const r = await semanticAssetService.graphOutline(
      props.nodes.map((n) => n.id), props.selId ? [props.selId] : [])
    cores.value = r?.cores ?? []
    checked.value = new Set(cores.value.map((c) => c.coreId))   // 默认全选(用户裁决)
  } catch { cores.value = [] }
  outlineLoading.value = false
})
</script>
