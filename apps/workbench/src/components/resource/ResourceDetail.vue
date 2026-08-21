<script setup lang="ts">
import type { Resource, ResourceListMeta } from '@/types'
import { XMarkIcon, HandThumbUpIcon, HandThumbDownIcon } from '@heroicons/vue/24/outline'
import { useAuthStore } from '@/stores/auth-store'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { resourceService } from '@/services/resource-service'

const props = defineProps<{ resource: Resource | null; show: boolean; meta: ResourceListMeta | null }>()
const emit = defineEmits<{ close: []; download: [id: number] }>()
const { t } = useI18n()
const auth = useAuthStore()

const labels = computed(() => props.meta?.labels || {})
const commentText = ref('')
const commentSubmitted = ref(false)
const commentSubmitting = ref(false)
const voting = ref(false)

const isPrerelease = computed(() => props.resource?.is_prerelease || props.resource?.status === 'prerelease')

function downloadLabel(r: Resource): string {
  const lbl = labels.value
  if (r.theme?.owned) return lbl.re_download || t('resource.action.reDownload')
  if (r.pricing_model === 'free') return lbl.download || t('resource.action.download')
  if (r.pricing_model === 'points') {
    const hasEnough = (auth.points || 0) >= (r.points_cost || 0)
    return hasEnough
      ? (lbl.points_exchange || t('resource.pricing.pointsExchange')).replace('{cost}', String(r.points_cost))
      : (lbl.points_insufficient || t('resource.pricing.pointsInsufficient')).replace('{cost}', String(r.points_cost))
  }
  if (r.pricing_model === 'paid' || r.pricing_model === 'subscription' || r.pricing_model === 'custom') return lbl.not_available || t('resource.notAvailable')
  return lbl.download || t('resource.action.download')
}

function canDownload(r: Resource): boolean {
  if (r.is_prerelease || r.status === 'prerelease') return false
  if (r.theme?.owned) return true
  if (r.pricing_model === 'free') return true
  if (r.pricing_model === 'points') return (auth.points || 0) >= (r.points_cost || 0)
  return false
}

function pricingInfo(r: Resource): string {
  const lbl = labels.value
  if (r.pricing_model === 'free') return lbl.free || t('resource.pricing.free')
  if (r.pricing_model === 'points') return (lbl.points_exchange || t('resource.pricing.points')).replace('{cost}', String(r.points_cost))
  if (r.pricing_model === 'paid') return `¥${r.price_cny}`
  if (r.pricing_model === 'subscription') return lbl.not_available || t('resource.notAvailable')
  if (r.pricing_model === 'custom') return lbl.not_available || t('resource.notAvailable')
  return ''
}

const isFree = computed(() => props.resource?.pricing_model === 'free')

function catColor(cat: string): string {
  const c = props.meta?.categories?.find(cc => cc.key === cat)
  return c?.color || 'var(--accent)'
}

async function handleVote(vote: number) {
  if (!props.resource || voting.value) return
  voting.value = true
  try {
    const result = await resourceService.vote(props.resource.id, vote)
    if (props.resource) {
      props.resource.like_count = result.like_count
      props.resource.dislike_count = result.dislike_count
      props.resource.my_vote = vote
    }
  } catch (err: any) {
    // silent
  } finally {
    voting.value = false
  }
}

async function handleSubmitComment() {
  if (!props.resource || !commentText.value.trim() || commentSubmitting.value) return
  commentSubmitting.value = true
  try {
    await resourceService.createComment(props.resource.id, commentText.value.trim())
    commentSubmitted.value = true
    commentText.value = ''
  } catch (err: any) {
    // silent
  } finally {
    commentSubmitting.value = false
  }
}

const likeActive = computed(() => props.resource?.my_vote === 1)
const dislikeActive = computed(() => props.resource?.my_vote === -1)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show && resource"
      class="modal-overlay"
      @click.self="$emit('close')"
    >
      <div class="modal resource-modal">
        <div class="modal-header">
          <span class="modal-title">{{ resource.title }}</span>
          <button
            class="btn btn-ghost btn-xs"
            @click="$emit('close')"
          >
            <XMarkIcon class="w-4 h-4" />
          </button>
        </div>
        <div class="modal-body">
          <div
            v-if="isPrerelease"
            class="prerelease-banner"
          >
            {{ t('resource.prerelease') }}
          </div>
          <div style="display:flex; gap:6px; margin-bottom:12px; flex-wrap:wrap;">
            <span
              class="detail-category"
              :style="{ background: catColor(resource.category) + '20', color: catColor(resource.category) }"
            >{{ resource.category }}</span>
            <span
              class="detail-price"
              :class="{ 'detail-price-free': isFree }"
            >{{ pricingInfo(resource) }}</span>
          </div>
          <p class="detail-desc">
            {{ resource.description }}
          </p>
          <div
            v-if="meta?.feature_flags?.show_detail_meta !== false && !isPrerelease"
            class="detail-meta"
          >
            <span>{{ (labels.download_count || '下载量') }}: {{ resource.download_count }}</span>
            <span>{{ (labels.publish_date || '发布时间') }}: {{ resource.created_at }}</span>
          </div>

          <div class="vote-section">
            <button
              class="vote-btn"
              :class="{ active: likeActive }"
              :disabled="!auth.isAuthenticated || voting"
              @click="handleVote(likeActive ? 0 : 1)"
            >
              <HandThumbUpIcon class="vote-icon" />
              <span>{{ resource.like_count ?? 0 }}</span>
            </button>
            <button
              class="vote-btn"
              :class="{ active: dislikeActive }"
              :disabled="!auth.isAuthenticated || voting"
              @click="handleVote(dislikeActive ? 0 : -1)"
            >
              <HandThumbDownIcon class="vote-icon" />
              <span>{{ resource.dislike_count ?? 0 }}</span>
            </button>
          </div>

          <div
            v-if="auth.isAuthenticated"
            class="comment-section"
          >
            <div class="comment-title">
              {{ t('resource.comment.title') }}
            </div>
            <div
              v-if="commentSubmitted"
              class="comment-hint"
            >
              {{ t('resource.comment.submitted') }}
            </div>
            <template v-if="!commentSubmitted">
              <textarea
                v-model="commentText"
                class="comment-input"
                :placeholder="t('resource.comment.placeholder')"
                maxlength="1000"
                rows="3"
              />
              <div class="comment-actions">
                <span class="comment-counter">{{ commentText.length }}/1000</span>
                <button
                  class="btn btn-primary btn-xs"
                  :disabled="!commentText.trim() || commentSubmitting"
                  @click="handleSubmitComment"
                >
                  {{ commentSubmitting ? t('resource.comment.submitting') : t('resource.comment.submit') }}
                </button>
              </div>
            </template>
          </div>
        </div>
        <div class="modal-footer">
          <button
            class="btn btn-ghost btn-sm"
            @click="$emit('close')"
          >
            {{ labels.close || '关闭' }}
          </button>
          <button
            v-if="!isPrerelease"
            class="btn btn-primary btn-sm"
            :disabled="!canDownload(resource)"
            @click="$emit('download', resource.id)"
          >
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
.detail-price-free { color: #22c55e; }
.detail-desc { font-size: 13px; color: var(--text-primary); line-height: 1.6; margin-bottom: 16px; }
.detail-meta { display: flex; gap: 16px; font-size: 11px; color: var(--text-muted); }
.prerelease-banner {
  background: #f59e0b; color: #fff; font-size: 12px; font-weight: 600;
  padding: 6px 12px; border-radius: 6px; margin-bottom: 12px; text-align: center;
}
.vote-section {
  display: flex; gap: 12px; margin-bottom: 16px; padding-top: 12px;
  border-top: 1px solid var(--border);
}
.vote-btn {
  display: flex; align-items: center; gap: 4px;
  padding: 4px 12px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-secondary); color: var(--text-muted); font-size: 12px;
  cursor: pointer; transition: all 0.15s;
}
.vote-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.vote-btn.active { border-color: var(--accent); color: var(--accent); background: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); }
.vote-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.vote-icon { width: 16px; height: 16px; }
.comment-section { margin-bottom: 8px; }
.comment-title { font-size: 12px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.comment-hint { font-size: 11px; color: var(--success); margin-bottom: 8px; }
.comment-input {
  width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-primary); color: var(--text-primary); font-size: 12px;
  resize: vertical; outline: none; box-sizing: border-box;
}
.comment-input:focus { border-color: var(--accent); }
.comment-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; }
.comment-counter { font-size: 11px; color: var(--text-muted); }
</style>
