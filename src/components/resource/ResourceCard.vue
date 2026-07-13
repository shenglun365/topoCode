<script setup lang="ts">
import type { Resource, ResourceListMeta } from '@/types'
import { ArrowDownTrayIcon, HandThumbUpIcon, HandThumbDownIcon } from '@heroicons/vue/24/outline'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ resource: Resource; meta: ResourceListMeta }>()
const emit = defineEmits<{ download: [id: number] }>()
const { t } = useI18n()

const catColor = computed(() => {
  const t = props.resource.theme
  if (t?.color) return t.color
  const cat = props.meta.categories?.find(c => c.key === props.resource.category)
  return cat?.color || '#6b7280'
})

const badgeText = computed(() => props.resource.theme?.badge_text || null)
const showDownloadCount = computed(() => props.meta.feature_flags?.show_download_count !== false)
const labels = computed(() => props.meta.labels || {})
const isPrerelease = computed(() => props.resource.is_prerelease || props.resource.status === 'prerelease')

function pricingLabel(r: Resource): string {
  const lbl = labels.value
  if (r.pricing_model === 'free') return lbl.free || t('resource.pricing.free')
  if (r.pricing_model === 'points') {
    return lbl.points_exchange?.replace('{cost}', String(r.points_cost)) || t('resource.pricing.points').replace('{cost}', String(r.points_cost))
  }
  if (r.pricing_model === 'paid') return `¥${r.price_cny}`
  if (r.pricing_model === 'subscription') return t('resource.pricing.subscription')
  if (r.pricing_model === 'custom') return t('resource.pricing.custom')
  return ''
}

function actionLabel(r: Resource): string {
  if (r.is_prerelease || r.status === 'prerelease') return t('resource.prerelease')
  const lbl = labels.value
  if (r.theme?.owned) return lbl.re_download || t('resource.action.reDownload')
  if (r.pricing_model === 'free') return lbl.download || t('resource.action.download')
  if (r.pricing_model === 'points') {
    return lbl.points_exchange?.replace('{cost}', String(r.points_cost)) || t('resource.pricing.points').replace('{cost}', String(r.points_cost))
  }
  return lbl.not_available || t('resource.notAvailable')
}

const isFree = computed(() => props.resource.pricing_model === 'free')
</script>

<template>
  <div
    class="resource-card card"
    @click="$emit('download', resource.id)"
  >
    <div
      class="card-thumb"
      :style="{ background: catColor }"
    >
      <span class="category-badge">{{ resource.category }}</span>
      <span
        v-if="pricingLabel(resource)"
        class="price-badge"
        :class="{ 'price-badge-free': isFree }"
      >{{ pricingLabel(resource) }}</span>
      <span
        v-if="badgeText"
        class="badge-hot"
      >{{ badgeText }}</span>
      <div class="badges-bottom">
        <span
          v-if="isPrerelease"
          class="badge-prerelease"
        >{{ t('resource.prerelease') }}</span>
        <span
          v-if="resource.status === 'offline' && resource.theme?.owned"
          class="badge-offline"
        >{{ labels.offline || t('resource.offline') }}</span>
        <span
          v-if="resource.theme?.owned"
          class="badge-owned"
        >{{ labels.owned || t('resource.owned') }}</span>
      </div>
    </div>
    <div class="card-body">
      <h3 class="card-title">
        {{ resource.title }}
      </h3>
      <p class="card-desc">
        {{ resource.description }}
      </p>
      <div class="card-footer">
        <div class="card-footer-left">
          <span
            v-if="showDownloadCount && !isPrerelease"
            class="download-count"
          >
            <ArrowDownTrayIcon class="w-3 h-3" />
            {{ resource.download_count }}
          </span>
          <span class="vote-counts">
            <HandThumbUpIcon class="vote-icon" />
            {{ resource.like_count ?? 0 }}
            <HandThumbDownIcon class="vote-icon vote-icon-down" />
            {{ resource.dislike_count ?? 0 }}
          </span>
        </div>
        <span
          v-if="resource.status !== 'offline'"
          class="btn-download"
          :class="{ 'btn-prerelease': isPrerelease }"
        >{{ actionLabel(resource) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.resource-card {
  display: flex; flex-direction: column; overflow: hidden; cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
  border-radius: var(--rc-card-radius, 8px);
  box-shadow: var(--rc-card-shadow, 0 1px 4px rgba(0,0,0,0.08));
  max-width: var(--rc-card-max-w, 220px);
}
.resource-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
.card-thumb { height: var(--rc-card-thumb-h, 100px); display: flex; align-items: flex-start; padding: 8px; position: relative; gap: 4px; }
.category-badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; background: rgba(255,255,255,0.2); color: #fff; }
.price-badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; background: rgba(0,0,0,0.3); color: #ffd700; margin-left: auto; }
.price-badge-free { color: #22c55e; }
.badge-hot {
  position: absolute; top: 4px; right: 4px;
  font-size: 9px; padding: 1px 6px; border-radius: 4px;
  background: #ef4444; color: #fff; font-weight: 600;
}
.badges-bottom {
  position: absolute; bottom: 4px; right: 4px;
  display: flex; gap: 4px;
}
.badge-prerelease {
  font-size: 9px; padding: 2px 8px; border-radius: 4px;
  background: #f59e0b; color: #fff; font-weight: 600;
}
.badge-offline {
  font-size: 9px; padding: 2px 8px; border-radius: 4px;
  background: rgba(156,163,175,0.85); color: #fff; font-weight: 600;
}
.badge-owned {
  font-size: 9px; padding: 2px 8px; border-radius: 4px;
  background: rgba(34,197,94,0.85); color: #fff; font-weight: 600;
}
.card-body { padding: 12px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
.card-title { font-size: 13px; font-weight: 600; color: var(--text-primary); line-height: 1.3; }
.card-desc { font-size: 11px; color: var(--text-muted); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-footer { display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: 8px; border-top: 1px solid var(--border); gap: var(--rc-card-gap, 12px); }
.card-footer-left { display: flex; flex-direction: column; gap: 2px; }
.download-count { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text-muted); }
.vote-counts { display: flex; align-items: center; gap: 3px; font-size: 10px; color: var(--text-muted); }
.vote-icon { width: 12px; height: 12px; }
.vote-icon-down { margin-left: 2px; }
.btn-download { font-size: 11px; padding: 3px 10px; border-radius: 4px; background: var(--accent); color: #fff; cursor: pointer; white-space: nowrap; }
.btn-prerelease { background: #f59e0b; }
</style>
