<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import { semanticAssetService } from '@/services/semantic-asset-service'

const { t } = useI18n()

/** 资产关联代码的伪码级说明(分层口径)：用户点击触发(不自动拉取)；
 *  有效生命周期内缓存(资产行 pseudo 字段)，腐烂失效后可重生成。 */
const props = defineProps<{ assetId: string; initial?: string }>()

const pseudo = ref(props.initial || '')
const loading = ref(false)
const degraded = ref(false)

async function gen(force = false) {
  if (loading.value) return
  loading.value = true
  try {
    const r = await semanticAssetService.pseudo(props.assetId, { force })
    pseudo.value = r.pseudo || ''
    degraded.value = !!r.degraded
  } catch {
    pseudo.value = ''
    degraded.value = true
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <div class="font-medium text-[10px] text-ctp-mauve mb-0.5 flex items-center gap-1.5">
      <span class="flex-1">{{ t('assetMgmt.pseudo') }}</span>
      <button
        v-if="pseudo"
        class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
        :disabled="loading"
        :title="t('assetMgmt.pseudoRegen')"
        @click="gen(true)"
      >
        <ArrowPathIcon class="w-3 h-3" :class="loading ? 'animate-spin' : ''" />
      </button>
    </div>
    <button
      v-if="!pseudo"
      class="btn btn-xs btn-ghost"
      :disabled="loading"
      @click="gen()"
    >
      <SparklesIcon class="w-3 h-3" :class="loading ? 'animate-pulse' : ''" />{{ t('assetMgmt.pseudoGenerate') }}
    </button>
    <template v-else>
      <pre class="pl-2 m-0 text-[10px] leading-relaxed whitespace-pre-wrap text-ctp-subtext0">{{ pseudo }}</pre>
      <div v-if="degraded" class="pl-2 text-[9px] text-ctp-overlay0">
        {{ t('assetMgmt.pseudoDegraded') }}
      </div>
    </template>
  </div>
</template>
