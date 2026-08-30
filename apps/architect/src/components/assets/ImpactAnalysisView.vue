<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, ArrowsRightLeftIcon, ChartBarIcon, CubeTransparentIcon } from '@heroicons/vue/24/outline'
import {
  semanticAssetService,
  type ImpactAnalysisResult,
} from '@/services/semantic-asset-service'

const { t } = useI18n()

const loading = ref(false)
const loaded = ref(false)
const data = ref<ImpactAnalysisResult | null>(null)

function kindLabel(k: string): string {
  const map: Record<string, string> = {
    entity: t('semanticAssets.kind.entity'),
    contract: t('semanticAssets.kind.contract'),
    state: t('semanticAssets.kind.state'),
    rule: t('semanticAssets.kind.rule'),
    process: t('semanticAssets.kind.process'),
    decision: t('semanticAssets.kind.decision'),
  }
  return map[k] ?? k
}

async function load() {
  loading.value = true
  try {
    data.value = await semanticAssetService.impact()
    loaded.value = true
  } catch (err: any) {
    console.warn('[impact] load failed:', err?.message)
  } finally {
    loading.value = false
  }
}

const hasData = () => {
  const d = data.value
  if (!d) return false
  return d.direct.length > 0 || d.propagated.length > 0 || d.drift.length > 0
    || d.coverage.verifiable > 0
}

onMounted(load)
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="panel-header">
      <span class="flex items-center gap-2">
        <ChartBarIcon class="w-4 h-4 text-ctp-sapphire" />{{ t('impact.title') }}
      </span>
      <button
        class="btn btn-sm btn-ghost"
        :disabled="loading"
        @click="load"
      >
        <ArrowPathIcon :class="['w-3.5 h-3.5', loading ? 'animate-spin' : '']" />
        {{ t('impact.refresh') }}
      </button>
    </div>
    <div class="p-3 space-y-4 text-xs">
      <p class="text-[11px] text-ctp-overlay1 -mt-1">{{ t('impact.subtitle') }}</p>

      <div v-if="!loaded || !data || !hasData()" class="flex items-center justify-center gap-2 py-6 text-ctp-overlay1">
        <CubeTransparentIcon class="w-5 h-5 text-ctp-overlay1/60" />{{ t('impact.noData') }}
      </div>

      <template v-else>
        <!-- 变更追踪（跨组件扩散链） -->
        <section class="space-y-2">
          <h3 class="flex items-center gap-1.5 font-medium text-ctp-text">
            <ArrowsRightLeftIcon class="w-3.5 h-3.5 text-ctp-sapphire" />{{ t('impact.changeTracking') }}
          </h3>
          <p class="text-[10px] text-ctp-overlay0">{{ t('impact.directHint') }}</p>
          <div
            v-if="data.direct.length"
            class="flex flex-wrap gap-1.5"
          >
            <span
              v-for="n in data.direct"
              :key="n.id"
              class="chip bg-ctp-yellow/15 text-ctp-yellow"
            >{{ n.name }} · {{ kindLabel(n.kind) }}</span>
          </div>
          <p v-else class="text-[11px] text-ctp-overlay0">{{ t('impact.emptyDirect') }}</p>

          <div v-if="data.propagated.length" class="mt-1">
            <div class="text-[10px] text-ctp-overlay0 mb-1">{{ t('impact.propagated') }}（{{ t('impact.propagatedHint') }}）</div>
            <div class="space-y-0.5">
              <div
                v-for="p in data.propagated"
                :key="p.id"
                class="flex items-center gap-1.5"
              >
                <span class="chip !text-[9px] bg-ctp-peach/15 text-ctp-peach shrink-0">{{ p.name }}</span>
                <span class="text-[10px] text-ctp-overlay0">{{ t('impact.dependsOn') }}</span>
                <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0 shrink-0">{{ p.viaName }}</span>
              </div>
            </div>
          </div>
          <p v-else class="text-[10px] text-ctp-overlay0 mt-1">{{ t('impact.emptyPropagated') }}</p>
        </section>

        <!-- 全局漂移（契约 ↔ 实现） -->
        <section class="space-y-2 border-t border-ctp-surface0 pt-3">
          <h3 class="flex items-center gap-1.5 font-medium text-ctp-text">
            <ChartBarIcon class="w-3.5 h-3.5 text-ctp-mauve" />{{ t('impact.globalDrift') }}
          </h3>
          <div class="flex items-center gap-4">
            <span class="text-ctp-subtext0">
              {{ t('impact.coverage') }}:
              <span class="font-medium" :class="data.coverage.pct >= 90 ? 'text-ctp-green' : data.coverage.pct >= 60 ? 'text-ctp-yellow' : 'text-ctp-red'">
                {{ data.coverage.pct }}%
              </span>
            </span>
            <span class="text-[11px] text-ctp-overlay0">
              {{ t('impact.covered') }} {{ data.coverage.covered }} / {{ t('impact.verifiable') }} {{ data.coverage.verifiable }}
            </span>
          </div>

          <div v-if="data.patterns.length" class="flex flex-wrap items-center gap-1.5">
            <span class="text-[10px] text-ctp-overlay0">{{ t('impact.patterns') }}:</span>
            <span
              v-for="p in data.patterns"
              :key="p.kind"
              class="chip bg-ctp-red/15 text-ctp-red"
            >{{ kindLabel(p.kind) }} × {{ p.count }}</span>
          </div>

          <div v-if="data.drift.length">
            <div class="space-y-0.5">
              <div
                v-for="x in data.drift"
                :key="x.itemId"
                class="flex items-center gap-1.5"
              >
                <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0 shrink-0 font-mono">{{ x.itemId }}</span>
                <span
                  class="chip !text-[9px] shrink-0"
                  :class="x.reason === 'intent' ? 'bg-ctp-surface0 text-ctp-overlay1' : 'bg-ctp-red/15 text-ctp-red'"
                >
                  {{ x.reason === 'intent' ? t('impact.intentOnly') : x.reason === 'missing' ? t('impact.missing') : t('impact.stale') }}
                </span>
                <span v-if="x.assetName" class="text-[10px] text-ctp-overlay0">{{ x.assetName }}</span>
                <span class="text-[10px] text-ctp-subtext0 truncate">{{ x.quote || kindLabel(x.kind) }}</span>
              </div>
            </div>
          </div>
          <p v-else class="text-[11px] text-ctp-green">{{ t('impact.noDrift') }}</p>
        </section>
      </template>
    </div>
  </div>
</template>
