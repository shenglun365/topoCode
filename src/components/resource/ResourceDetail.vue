<script setup lang="ts">
import type { Resource, ResourceListMeta } from '@/types'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { useAuthStore } from '@/stores/auth-store'
import { computed } from 'vue'

const props = defineProps<{ resource: Resource | null; show: boolean; meta: ResourceListMeta | null }>()
const emit = defineEmits<{ close: []; download: [id: number] }>()
const auth = useAuthStore()

const labels = computed(() => props.meta?.labels || {})

function downloadLabel(r: Resource): string {
  const lbl = labels.value
  if (r.theme?.owned) return lbl.re_download || '重新下载'
  if (r.pricing_model === 'free') return lbl.download || '下载'
  if (r.pricing_model === 'points') {
    const hasEnough = (auth.points || 0) >= (r.points_cost || 0)
    return hasEnough
      ? (lbl.points_exchange || '{cost} 积分兑换').replace('{cost}', String(r.points_cost))
      : (lbl.points_insufficient || '积分不足（需 {cost}）').replace('{cost}', String(r.points_cost))
  }
  if (r.pricing_model === 'paid') return `¥${r.price_cny} 购买`
  if (r.pricing_model === 'subscription') return '订阅会员'
  if (r.pricing_model === 'custom') return '联系客服'
  return lbl.download || '下载'
}

function canDownload(r: Resource): boolean {
  if (r.theme?.owned) return true
  if (r.pricing_model === 'free') return true
  if (r.pricing_model === 'points') return (auth.points || 0) >= (r.points_cost || 0)
  return false
}

function pricingInfo(r: Resource): string {
  const lbl = labels.value
  if (r.pricing_model === 'free') return lbl.free || '免费'
  if (r.pricing_model === 'points') return (lbl.points_exchange || '{cost} 积分').replace('{cost}', String(r.points_cost))
  if (r.pricing_model === 'paid') return `¥${r.price_cny}`
  if (r.pricing_model === 'subscription') return '需要订阅会员'
  if (r.pricing_model === 'custom') return '专属定制'
  return ''
}

function catColor(cat: string): string {
  const c = props.meta?.categories?.find(cc => cc.key === cat)
  return c?.color || 'var(--accent)'
}
</script>

<template>
  <Teleport to="body">
    <div v-if="show && resource" class="modal-overlay" @click.self="$emit('close')">
      <div class="modal resource-modal">
        <div class="modal-header">
          <span class="modal-title">{{ resource.title }}</span>
          <button class="btn btn-ghost btn-xs" @click="$emit('close')">
            <XMarkIcon class="w-4 h-4" />
          </button>
        </div>
        <div class="modal-body">
          <div style="display:flex; gap:6px; margin-bottom:12px; flex-wrap:wrap;">
            <span class="detail-category" :style="{ background: catColor(resource.category) + '20', color: catColor(resource.category) }">{{ resource.category }}</span>
            <span class="detail-price">{{ pricingInfo(resource) }}</span>
          </div>
          <p class="detail-desc">{{ resource.description }}</p>
          <div v-if="meta?.feature_flags?.show_detail_meta !== false" class="detail-meta">
            <span>{{ (labels.download_count || '下载量') }}: {{ resource.download_count }}</span>
            <span>{{ (labels.publish_date || '发布时间') }}: {{ resource.created_at }}</span>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost btn-sm" @click="$emit('close')">{{ labels.close || '关闭' }}</button>
          <button
            class="btn btn-primary btn-sm"
            :disabled="!canDownload(resource)"
            @click="$emit('download', resource.id)">
            {{ downloadLabel(resource) }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: flex; align-items: center; justify-content: center; z-index: 10000; }
.modal { background: var(--bg-primary); border: 1px solid var(--border); border-radius: var(--rc-detail-radius, 10px); max-width: var(--rc-detail-max-w, 500px); width: 90vw; overflow: hidden; }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid var(--border); }
.modal-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.modal-body { padding: 18px; }
.modal-footer { display: flex; gap: 6px; justify-content: flex-end; padding: 12px 18px; border-top: 1px solid var(--border); }
.detail-category { display: inline-block; font-size: 10px; padding: 2px 10px; border-radius: 10px; }
.detail-price { display: inline-block; font-size: 10px; padding: 2px 10px; border-radius: 10px; background: var(--bg-tertiary); color: #ffd700; font-weight: 600; }
.detail-desc { font-size: 13px; color: var(--text-primary); line-height: 1.6; margin-bottom: 16px; }
.detail-meta { display: flex; gap: 16px; font-size: 11px; color: var(--text-muted); }
</style>
