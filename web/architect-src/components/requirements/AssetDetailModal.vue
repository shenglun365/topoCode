<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CubeIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import type { AssetDetail, AssetScopeItem, FlowStep } from '@/types'
import { kbAssetService } from '@/services/kb-assets'

const props = defineProps<{ open: boolean; asset: AssetScopeItem | null }>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()

const detailLoading = ref(false)
const detailMiss = ref(false)
const detailData = ref<AssetDetail | null>(null)

watch(
  () => props.open,
  async (v) => {
    if (!v || !props.asset) return
    detailData.value = null
    detailMiss.value = false
    detailLoading.value = true
    const d = await kbAssetService.detail(props.asset.assetId)
    detailLoading.value = false
    if (d) detailData.value = d
    else detailMiss.value = true
  },
)

const changeLabel = (change: string) => t(`architecture.change.${change}`)

function detailLabelOf(): string {
  const d = detailData.value
  if (!d) return ''
  switch (d.type) {
    case 'component': return t(`architecture.kind.${d.kind ?? 'service'}`)
    case 'er': return t(`asset.entityKind.table`)
    case 'orm': return 'ORM'
    case 'entity': return t(`asset.entityKind.${d.entityKind ?? 'class'}`)
    default: return changeLabel(d.change)
  }
}

function stepTypeOf(s: FlowStep): string {
  return { action: '去', decision: '判', io: '入', sync: '同' }[s.type] ?? ''
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
    @click.self="emit('close')"
  >
    <div class="panel w-full max-w-xl max-h-[80vh] overflow-hidden flex flex-col">
      <div class="panel-header shrink-0">
        <span class="flex items-center gap-2">
          <CubeIcon class="w-4 h-4 text-ctp-blue" />{{ t('requirement.form.assetDetailTitle') }}
        </span>
        <button
          class="btn btn-xs btn-ghost"
          @click="emit('close')"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      <div class="flex-1 min-h-0 overflow-auto p-3">
        <p
          v-if="detailLoading"
          class="text-xs text-ctp-overlay1"
        >
          {{ t('requirement.form.assetDetailLoading') }}
        </p>
        <template v-else-if="detailMiss">
          <p class="text-xs text-ctp-peach mb-2">
            {{ t('requirement.form.assetDetailMiss') }}
          </p>
          <div class="flex flex-wrap items-center gap-1.5 text-[11px] text-ctp-subtext0">
            <span class="chip bg-ctp-surface0 font-mono">{{ asset?.assetId }}</span>
            <span class="chip">{{ t(`requirement.assetRole.${asset?.role === 'core' ? 'core' : 'related'}`) }}</span>
            <span
              v-if="asset?.file"
              class="chip bg-ctp-surface0 font-mono"
            >{{ asset.file }}</span>
          </div>
        </template>
        <template v-else-if="detailData">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="chip bg-ctp-blue/15 text-ctp-blue font-mono">{{ detailData.assetId }}</span>
            <span class="chip bg-ctp-surface0">{{ detailData.name }}</span>
            <span class="chip bg-ctp-surface0">{{ detailLabelOf() }}</span>
            <span class="chip bg-ctp-surface0">{{ changeLabel(detailData.change) }}</span>
            <span
              v-if="asset?.role"
              class="chip bg-ctp-surface0"
            >{{ t(`requirement.assetRole.${asset.role}`) }}</span>
          </div>
          <div class="mt-3 space-y-3 text-xs">
            <div>
              <div class="text-[10px] text-ctp-overlay1 mb-0.5">
                {{ t('requirement.form.assetDetail.desc') }}
              </div>
              <p class="text-ctp-subtext1">
                {{ detailData.desc || '—' }}
              </p>
            </div>
            <div class="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ctp-overlay1">
              <span
                v-if="detailData.file"
                class="font-mono"
              >{{ detailData.file }}</span>
              <span v-if="detailData.lang">{{ t('requirement.form.assetDetail.lang') }}: {{ detailData.lang }}</span>
            </div>

            <!-- 组件 -->
            <div v-if="detailData.type === 'component'">
              <div class="text-[10px] text-ctp-overlay1 mb-1">
                {{ t('requirement.form.assetDetail.responsibilities') }}
              </div>
              <ul class="space-y-1">
                <li
                  v-for="r in detailData.responsibilities ?? []"
                  :key="r"
                  class="flex items-start gap-1.5 text-ctp-subtext1"
                >
                  <span class="mt-0.5 w-1 h-1 rounded-full bg-ctp-peach shrink-0" />{{ r }}
                </li>
              </ul>
              <div
                v-if="detailData.owns?.length"
                class="text-[10px] text-ctp-overlay1 mt-2 mb-1"
              >
                {{ t('requirement.form.assetDetail.owns') }}
              </div>
              <div
                v-if="detailData.owns?.length"
                class="flex flex-wrap gap-1.5"
              >
                <span
                  v-for="o in detailData.owns"
                  :key="o"
                  class="chip bg-ctp-surface0"
                >{{ o }}</span>
              </div>
              <div
                v-if="detailData.dependsOn?.length"
                class="text-[10px] text-ctp-overlay1 mt-2 mb-1"
              >
                {{ t('requirement.form.assetDetail.dependsOn') }}
              </div>
              <div
                v-if="detailData.dependsOn?.length"
                class="flex flex-wrap gap-1.5"
              >
                <span
                  v-for="d in detailData.dependsOn"
                  :key="d"
                  class="chip bg-ctp-surface0"
                >{{ d }}</span>
              </div>
            </div>

            <!-- 数据结构：ER 表 -->
            <div v-else-if="detailData.type === 'er'">
              <div
                v-if="detailData.ast"
                class="rounded-lg border border-ctp-surface0 px-2 py-1.5 font-mono text-[10px] text-ctp-sapphire mb-2"
              >
                {{ detailData.ast.file }} {{ detailData.ast.symbol }} L{{ detailData.ast.startLine }}-{{ detailData.ast.endLine }}
              </div>
              <div class="text-[10px] text-ctp-overlay1 mb-1">
                {{ t('requirement.form.assetDetail.columns') }}
              </div>
              <div class="rounded-lg border border-ctp-surface0 divide-y divide-ctp-surface0">
                <div
                  v-for="f in detailData.columns ?? []"
                  :key="f.name"
                  class="grid grid-cols-12 gap-1 px-2 py-1 text-[11px]"
                >
                  <span class="col-span-3 font-mono text-ctp-peach">{{ f.name }}</span>
                  <span class="col-span-2 font-mono text-ctp-sapphire">{{ f.type }}</span>
                  <span class="col-span-7 text-ctp-subtext1">{{ f.desc }}</span>
                </div>
              </div>
              <div
                v-if="detailData.relations?.length"
                class="flex flex-wrap gap-1.5 mt-2"
              >
                <span
                  v-for="r in detailData.relations"
                  :key="`${r.from}-${r.to}-${r.key}`"
                  class="chip bg-ctp-surface0"
                >{{ r.from }} {{ r.type }} {{ r.to }} ({{ r.key }})</span>
              </div>
              <div
                v-if="detailData.invariants?.length"
                class="flex flex-wrap gap-1.5 mt-2"
              >
                <span
                  v-for="iv in detailData.invariants"
                  :key="iv"
                  class="chip bg-ctp-surface0"
                >{{ iv }}</span>
              </div>
            </div>

            <!-- 数据结构：ORM 映射 -->
            <div v-else-if="detailData.type === 'orm'">
              <div
                v-if="detailData.ast"
                class="rounded-lg border border-ctp-surface0 px-2 py-1.5 font-mono text-[10px] text-ctp-sapphire mb-2"
              >
                {{ detailData.ast.file }} {{ detailData.ast.symbol }} L{{ detailData.ast.startLine }}-{{ detailData.ast.endLine }}
              </div>
              <div class="flex items-center gap-2 mb-2 text-[11px]">
                <span class="chip bg-ctp-surface0">{{ detailData.entity }}</span>
                <span class="text-ctp-overlay1">↔</span>
                <span class="chip bg-ctp-surface0">{{ detailData.table }}</span>
              </div>
              <div class="text-[10px] text-ctp-overlay1 mb-1">
                {{ t('requirement.form.assetDetail.ormFields') }}
              </div>
              <div class="rounded-lg border border-ctp-surface0 divide-y divide-ctp-surface0">
                <div
                  v-for="f in detailData.ormFields ?? []"
                  :key="f.entityField"
                  class="grid grid-cols-12 gap-1 px-2 py-1 text-[11px]"
                >
                  <span class="col-span-3 font-mono text-ctp-peach">{{ f.entityField }}</span>
                  <span class="col-span-3 font-mono text-ctp-sapphire">{{ f.column }}</span>
                  <span class="col-span-6 text-ctp-subtext1">{{ f.desc }}</span>
                </div>
              </div>
            </div>

            <!-- 数据结构：程序内实体类 -->
            <div v-else-if="detailData.type === 'entity'">
              <div
                v-if="detailData.ast"
                class="rounded-lg border border-ctp-surface0 px-2 py-1.5 font-mono text-[10px] text-ctp-sapphire mb-2"
              >
                {{ detailData.ast.file }} {{ detailData.ast.symbol }} L{{ detailData.ast.startLine }}-{{ detailData.ast.endLine }}
              </div>
              <div class="text-[10px] text-ctp-overlay1 mb-1">
                {{ t('requirement.form.assetDetail.fields') }}
              </div>
              <div class="rounded-lg border border-ctp-surface0 divide-y divide-ctp-surface0">
                <div
                  v-for="f in detailData.fields ?? []"
                  :key="f.name"
                  class="grid grid-cols-12 gap-1 px-2 py-1 text-[11px]"
                >
                  <span class="col-span-3 font-mono text-ctp-peach">{{ f.name }}</span>
                  <span class="col-span-2 font-mono text-ctp-sapphire">{{ f.type }}</span>
                  <span class="col-span-7 text-ctp-subtext1">{{ f.desc }}</span>
                </div>
              </div>
              <div
                v-if="detailData.methods?.length"
                class="text-[10px] text-ctp-overlay1 mt-2 mb-1"
              >
                {{ t('requirement.form.assetDetail.methods') }}
              </div>
              <div
                v-if="detailData.methods?.length"
                class="space-y-1"
              >
                <div
                  v-for="m in detailData.methods"
                  :key="m.name"
                  class="flex items-center gap-2 text-[11px]"
                >
                  <span class="font-mono text-ctp-mauve">{{ m.signature }}</span>
                  <span class="text-ctp-subtext1">{{ m.desc }}</span>
                </div>
              </div>
            </div>

            <!-- 执行流程 -->
            <div v-else-if="detailData.type === 'flow'">
              <div
                v-if="detailData.trigger"
                class="text-[11px] text-ctp-subtext0"
              >
                <span class="text-ctp-overlay1">{{ t('requirement.form.assetDetail.trigger') }}:</span>
                <span class="ml-1">{{ detailData.trigger }}</span>
              </div>
              <div class="text-[10px] text-ctp-overlay1 mt-2 mb-1">
                {{ t('requirement.form.assetDetail.steps') }}
              </div>
              <div class="space-y-1">
                <div
                  v-for="s in detailData.steps ?? []"
                  :key="s.id"
                  class="flex items-center gap-2 text-[11px]"
                >
                  <span class="w-4 h-4 shrink-0 rounded bg-ctp-surface0 text-ctp-mauve flex items-center justify-center text-[9px]">{{ stepTypeOf(s) }}</span>
                  <span class="text-ctp-subtext1">{{ s.label }}</span>
                  <span
                    v-if="s.owner"
                    class="ml-auto chip bg-ctp-surface0"
                  >{{ t('requirement.form.assetDetail.owner') }}: {{ s.owner }}</span>
                </div>
              </div>
            </div>

            <!-- 数据流 -->
            <div v-else-if="detailData.type === 'dataflow'">
              <div class="text-[10px] text-ctp-overlay1 mb-1">
                {{ t('requirement.form.assetDetail.streams') }}
              </div>
              <div class="space-y-1">
                <div
                  v-for="str in detailData.streams ?? []"
                  :key="str.id"
                  class="rounded-lg border border-ctp-surface0 px-2 py-1.5 text-[11px]"
                >
                  <div class="flex items-center gap-2">
                    <span class="font-mono text-ctp-sapphire">{{ str.name }}</span>
                    <span class="text-ctp-overlay1">{{ str.from }}</span>
                    <span class="text-ctp-peach">→</span>
                    <span class="text-ctp-overlay1">{{ str.to }}</span>
                    <span
                      v-if="str.channel"
                      class="chip bg-ctp-surface0 ml-auto"
                    >{{ str.channel }}</span>
                  </div>
                  <div
                    v-if="str.payload"
                    class="text-ctp-subtext0 mt-0.5"
                  >
                    {{ str.payload }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>