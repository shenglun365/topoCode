<template>
  <div class="flex min-h-0 flex-1 flex-col text-xs">
    <!-- 顶栏: 统计 + 新建规约 -->
    <div class="flex shrink-0 items-center gap-2 px-1 pb-1.5">
      <span class="text-[11px] font-semibold text-ctp-text">{{ t('guard.title') }}</span>
      <span class="chip bg-ctp-teal/15 text-ctp-teal !text-[9px]">
        {{ t('guard.statsRules', { n: coreRules.rules.value.length }) }}
      </span>
      <span class="chip bg-ctp-yellow/15 text-ctp-yellow !text-[9px]">
        {{ t('guard.statsTargets', { n: coreRules.effective.value.length }) }}
      </span>
      <span class="flex-1" />
      <button
        class="btn btn-xs btn-teal inline-flex items-center gap-1"
        @click="openNewRule"
      ><PlusIcon class="h-3 w-3" />{{ t('guard.newRule') }}</button>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto rounded-lg border border-ctp-surface1">
      <p
        v-if="coreRules.loading.value && !coreRules.loaded.value"
        class="py-6 text-center text-ctp-overlay0"
      >{{ t('common.loading') }}</p>
      <p
        v-else-if="!rows.length"
        class="px-3 py-6 text-center text-[11px] leading-relaxed text-ctp-overlay0"
      >{{ t('guard.empty') }}</p>
      <template v-else>
        <template v-for="comp in rows" :key="comp.key">
          <!-- 组件组头(component 挂载点) -->
          <div
            class="flex items-center gap-1.5 border-b border-ctp-surface0 px-2 py-1.5 hover:bg-ctp-surface0/40"
            :data-guard-target="comp.key"
          >
            <button class="text-ctp-overlay0 hover:text-ctp-text p-0.5" @click="toggle(comp.key)">
              <ChevronRightIcon class="h-3 w-3 transition-transform" :class="openSet.has(comp.key) ? 'rotate-90' : ''" />
            </button>
            <ServerStackIcon class="h-3.5 w-3.5 shrink-0 text-ctp-mauve" />
            <span class="shrink-0 font-semibold text-ctp-text">{{ comp.title }}</span>
            <span class="shrink-0 font-mono text-[9px] text-ctp-overlay0">{{ comp.key }}</span>
            <span class="flex-1" />
            <RuleChips
              :target-type="'component'"
              :target-id="comp.key"
              :title="comp.title"
              :core-rules="coreRules"
              @locate-rule="openEdit"
              @new-rule="openNewRule"
            />
          </div>
          <template v-if="openSet.has(comp.key)">
            <template v-for="file in comp.files" :key="comp.key + ':' + file.path">
              <!-- 文件子组(file 挂载点) -->
              <div
                class="flex items-center gap-1.5 border-b border-ctp-surface0 bg-ctp-surface0/20 px-2 py-1 pl-6 hover:bg-ctp-surface0/40"
                :data-guard-target="file.path"
              >
                <button class="text-ctp-overlay0 hover:text-ctp-text p-0.5" @click="toggle(file.path)">
                  <ChevronRightIcon class="h-3 w-3 transition-transform" :class="openSet.has(file.path) ? 'rotate-90' : ''" />
                </button>
                <CodeBracketIcon class="h-3 w-3 shrink-0 text-ctp-sapphire" />
                <span class="shrink-0 font-mono text-[10px] text-ctp-subtext1">{{ file.path }}</span>
                <span class="flex-1" />
                <RuleChips
                  :target-type="'file'"
                  :target-id="file.path"
                  :title="file.path"
                  :core-rules="coreRules"
                  @locate-rule="openEdit"
              @new-rule="openNewRule"
                />
              </div>
              <!-- 资产行(asset 挂载点) -->
              <div
                v-for="a in file.assets"
                :key="a.id"
                class="flex items-center gap-1.5 border-b border-ctp-surface0 px-2 py-1 pl-10 hover:bg-ctp-surface0/40"
                :data-guard-target="a.id"
              >
                <span class="chip shrink-0 !text-[8px] bg-ctp-mauve/15 text-ctp-mauve">{{ t(`assetMgmt.kind.${a.kind}`) }}</span>
                <span class="min-w-0 flex-1 truncate text-ctp-text" :title="a.id">{{ a.title }}</span>
                <span class="flex-1" />
                <RuleChips
                  :target-type="'asset'"
                  :target-id="a.id"
                  :title="a.title"
                  :core-rules="coreRules"
                  @locate-rule="openEdit"
              @new-rule="openNewRule"
                />
              </div>
            </template>
          </template>
        </template>
      </template>
    </div>

    <p class="shrink-0 px-1 pt-1.5 text-[10px] text-ctp-overlay0">{{ t('guard.hint') }}</p>

    <RuleDefModal
      v-if="modalRule !== undefined"
      :rule="modalRule"
      @close="modalRule = undefined"
      @saved="coreRules.refresh()"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 核心守护列表(2610 重构): 多级(组件→文件→资产) 挂载规约。
 * - 三层行均为挂载点; 行右侧 = 已挂规约 chips + 挂规约下拉(RuleChips 内联组件)
 * - 数据源: ws items(语义资产, 含组件归属/锚点文件) — 与语义树同源
 * - ★ 跳转定位: 外部传 locate(目标 id) → scrollIntoView + 闪高亮
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronRightIcon, CodeBracketIcon, PlusIcon, ServerStackIcon } from '@heroicons/vue/24/outline'
import { useAssetWorkspaceCtx } from '..'
import { useCoreRules } from '../useCoreRules'
import RuleDefModal from './RuleDefModal.vue'
import RuleChips from './RuleChips.vue'
import type { RuleDef } from '../useCoreRules'

const props = defineProps<{ locate?: string }>()
const { t } = useI18n()
const coreRules = useCoreRules()
const { items, componentsOf } = useAssetWorkspaceCtx()

onMounted(() => { void coreRules.refresh() })

interface AssetRow { id: string; title: string; kind: string }
interface FileRow { path: string; assets: AssetRow[] }
interface CompRow { key: string; title: string; files: FileRow[] }

const openSet = ref<Set<string>>(new Set())

function toggle(key: string) {
  const s = new Set(openSet.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  openSet.value = s
}

/** 多级行装配: 组件→文件→资产(未归属资产归 OTHER 组; 文件按资产首锚点)。 */
const OTHER = '__other__'
const rows = computed<CompRow[]>(() => {
  const live = items.value.filter((a) => a.status !== 'deleted')
  const compMap = new Map<string, CompRow>()
  const ensure = (key: string, title: string): CompRow => {
    let row = compMap.get(key)
    if (!row) {
      row = { key, title, files: [] }
      compMap.set(key, row)
    }
    return row
  }
  for (const a of live) {
    const file = a.astRefs?.[0]?.file || '(无锚点)'
    const comps = componentsOf(a)
    if (comps.length) {
      for (const cid of comps) {
        const row = ensure(cid, cid)
        let fr = row.files.find((f) => f.path === file)
        if (!fr) {
          fr = { path: file, assets: [] }
          row.files.push(fr)
        }
        fr.assets.push({ id: a.id, title: a.name || a.id, kind: a.kind || 'entity' })
      }
    } else {
      const row = ensure(OTHER, t('assetMgmt.unownedFiles'))
      let fr = row.files.find((f) => f.path === file)
      if (!fr) {
        fr = { path: file, assets: [] }
        row.files.push(fr)
      }
      fr.assets.push({ id: a.id, title: a.name || a.id, kind: a.kind || 'entity' })
    }
  }
  // 无锚点文件的组件级/文件级纯挂载目标(挂了规约但列表无行) → 补组
  for (const e of coreRules.effective.value) {
    if (e.targetType !== 'component' || compMap.has(e.targetId)) continue
    compMap.set(e.targetId, { key: e.targetId, title: e.title || e.targetId, files: [] })
  }
  return [...compMap.values()]
})

// ---- 规约编辑弹窗 ----
const modalRule = ref<RuleDef | null | undefined>(undefined)
function openNewRule() {
  modalRule.value = null
}

function openEdit(ruleId: string) {
  const rd = coreRules.rules.value.find((x) => x.id === ruleId)
  if (rd) modalRule.value = rd
}

// ---- ★ 跳转定位 ----
watch(() => props.locate, async (v) => {
  if (!v) return
  await nextTick()
  const el = document.querySelector(`[data-guard-target="${CSS.escape(v)}"]`)
  if (el) {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    el.classList.add('guard-locate-flash')
    setTimeout(() => el.classList.remove('guard-locate-flash'), 2200)
  }
})
</script>

<style scoped>
.guard-locate-flash {
  animation: guard-flash 2.2s ease;
}
@keyframes guard-flash {
  0%, 60% { background: rgba(249, 226, 175, 0.18); }
  100% { background: transparent; }
}
</style>
