<script setup lang="ts">
import type { Resource } from '@/types'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { useAuthStore } from '@/stores/auth-store'

defineProps<{ resource: Resource | null; show: boolean }>()
const emit = defineEmits<{ close: []; download: [id: number] }>()
const auth = useAuthStore()

function downloadLabel(r: Resource): string {
  if (r.pricing_model === 'free') return '下载'
  if (r.pricing_model === 'points') {
    const hasEnough = (auth.points || 0) >= (r.points_cost || 0)
    return hasEnough ? `${r.points_cost} 积分兑换` : `积分不足（需 ${r.points_cost}）`
  }
  if (r.pricing_model === 'paid') return `¥${r.price_cny} 购买`
  if (r.pricing_model === 'subscription') return '订阅会员'
  if (r.pricing_model === 'custom') return '联系客服'
  return '下载'
}

function canDownload(r: Resource): boolean {
  if (r.pricing_model === 'free') return true
  if (r.pricing_model === 'points') return (auth.points || 0) >= (r.points_cost || 0)
  return false
}

function pricingInfo(r: Resource): string {
  if (r.pricing_model === 'free') return '免费'
  if (r.pricing_model === 'points') return `${r.points_cost} 积分`
  if (r.pricing_model === 'paid') return `¥${r.price_cny}`
  if (r.pricing_model === 'subscription') return '需要订阅会员'
  if (r.pricing_model === 'custom') return '专属定制'
  return ''
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
          <div style="display:flex; gap:6px; margin-bottom:12px;">
            <span class="detail-category">{{ resource.category }}</span>
            <span class="detail-price">{{ pricingInfo(resource) }}</span>
          </div>
          <p class="detail-desc">{{ resource.description }}</p>
          <div class="detail-meta">
            <span>{{ '下载量' }}: {{ resource.download_count }}</span>
            <span>{{ '发布时间' }}: {{ resource.created_at }}</span>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost btn-sm" @click="$emit('close')">{{ '关闭' }}</button>
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
.modal { background: var(--bg-primary); border: 1px solid var(--border); border-radius: 10px; max-width: 500px; width: 90vw; overflow: hidden; }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid var(--border); }
.modal-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.modal-body { padding: 18px; }
.modal-footer { display: flex; gap: 6px; justify-content: flex-end; padding: 12px 18px; border-top: 1px solid var(--border); }
.detail-category { display: inline-block; font-size: 10px; padding: 2px 10px; border-radius: 10px; background: var(--bg-tertiary); color: var(--accent); }
.detail-price { display: inline-block; font-size: 10px; padding: 2px 10px; border-radius: 10px; background: var(--bg-tertiary); color: #ffd700; font-weight: 600; }
.detail-desc { font-size: 13px; color: var(--text-primary); line-height: 1.6; margin-bottom: 16px; }
.detail-meta { display: flex; gap: 16px; font-size: 11px; color: var(--text-muted); }
</style>