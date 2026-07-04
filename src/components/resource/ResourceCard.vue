<script setup lang="ts">
import type { Resource } from '@/types'
import { ArrowDownTrayIcon } from '@heroicons/vue/24/outline'

defineProps<{ resource: Resource }>()
const emit = defineEmits<{ download: [id: number] }>()

const categoryColors: Record<string, string> = {
  '微服务': '#6366f1',
  '前端': '#3b82f6',
  '云原生': '#06b6d4',
  'AI': '#8b5cf6',
  '游戏': '#ec4899',
}

function pricingLabel(r: Resource): string {
  if (r.pricing_model === 'free') return ''
  if (r.pricing_model === 'points') return `${r.points_cost} 积分`
  if (r.pricing_model === 'paid') return `¥${r.price_cny}`
  if (r.pricing_model === 'subscription') return '会员'
  if (r.pricing_model === 'custom') return '定制'
  return ''
}
</script>

<template>
  <div class="resource-card card" @click="$emit('download', resource.id)">
    <div class="card-thumb" :style="{ background: categoryColors[resource.category] || '#6b7280' }">
      <span class="category-badge">{{ resource.category }}</span>
      <span v-if="pricingLabel(resource)" class="price-badge">{{ pricingLabel(resource) }}</span>
    </div>
    <div class="card-body">
      <h3 class="card-title">{{ resource.title }}</h3>
      <p class="card-desc">{{ resource.description }}</p>
      <div class="card-footer">
        <span class="download-count">
          <ArrowDownTrayIcon class="w-3 h-3" />
          {{ resource.download_count }}
        </span>
        <span class="btn-download">{{ '下载' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.resource-card {
  display: flex; flex-direction: column; overflow: hidden; cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}
.resource-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
.card-thumb { height: 100px; display: flex; align-items: flex-start; padding: 8px; position: relative; gap: 4px; }
.category-badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; background: rgba(255,255,255,0.2); color: #fff; }
.price-badge { font-size: 10px; padding: 2px 8px; border-radius: 10px; background: rgba(0,0,0,0.3); color: #ffd700; margin-left: auto; }
.card-body { padding: 12px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
.card-title { font-size: 13px; font-weight: 600; color: var(--text-primary); line-height: 1.3; }
.card-desc { font-size: 11px; color: var(--text-muted); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-footer { display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: 8px; border-top: 1px solid var(--border); }
.download-count { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text-muted); }
.btn-download { font-size: 11px; padding: 3px 10px; border-radius: 4px; background: var(--accent); color: #fff; cursor: pointer; }
</style>