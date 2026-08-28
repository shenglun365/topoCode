<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { semanticAssetService } from '@/services/semantic-asset-service'

const { t } = useI18n()

/** 资产关联代码的伪码级说明：查询时懒生成 + 有效生命周期内缓存。
 *  initial 有值(列表已带回缓存)则直接展示，否则按需向后端生成。 */
const props = defineProps<{ assetId: string; initial?: string }>()

const loading = ref(!props.initial)
const pseudo = ref(props.initial || '')
const degraded = ref(false)

onMounted(async () => {
  if (pseudo.value) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const r = await semanticAssetService.pseudo(props.assetId)
    pseudo.value = r.pseudo || ''
    degraded.value = !!r.degraded
  } catch {
    pseudo.value = ''
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <div class="font-medium text-[10px] text-ctp-mauve mb-0.5">
      {{ t('assetMgmt.pseudo') }}
    </div>
    <div v-if="loading" class="pl-2 text-[10px] text-ctp-overlay0 animate-pulse">
      {{ t('assetMgmt.pseudoLoading') }}
    </div>
    <pre v-else-if="pseudo" class="pl-2 m-0 text-[10px] leading-relaxed whitespace-pre-wrap text-ctp-subtext0">{{ pseudo }}</pre>
    <div v-else class="pl-2 text-[10px] text-ctp-overlay0">—</div>
    <div v-if="degraded && pseudo" class="pl-2 text-[9px] text-ctp-overlay0">
      {{ t('assetMgmt.pseudoDegraded') }}
    </div>
  </div>
</template>
