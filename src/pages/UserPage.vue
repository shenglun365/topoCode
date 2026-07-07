<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  UserIcon,
  ArrowDownTrayIcon,
  CurrencyDollarIcon,
  DocumentTextIcon,
} from '@heroicons/vue/24/outline'
import { useResourceStore } from '@/stores/resource-store'
import { useAuthStore } from '@/stores/auth-store'
import ProfileTab from '@/components/user/ProfileTab.vue'
import AccountTab from '@/components/user/AccountTab.vue'
import OrderTab from '@/components/user/OrderTab.vue'
import ResourceCard from '@/components/resource/ResourceCard.vue'
import ResourceDetail from '@/components/resource/ResourceDetail.vue'
import { useComponentId } from '@/composables/useComponentId'
import type { ResourceListMeta } from '@/types'

const { showId, componentId } = useComponentId('PG-005')
const { t } = useI18n()
const resourceStore = useResourceStore()
const authStore = useAuthStore()

const activeTab = ref<'profile' | 'account' | 'order' | 'resource'>('profile')
const showDetail = ref(false)
const pageUserRef = ref<HTMLElement | null>(null)

const tabs = [
  { id: 'profile' as const, key: 'settings.profile', icon: UserIcon },
  { id: 'account' as const, key: 'auth.account', icon: CurrencyDollarIcon },
  { id: 'order' as const, key: 'auth.order', icon: DocumentTextIcon },
  { id: 'resource' as const, key: 'settings.resourceCenter', icon: ArrowDownTrayIcon },
]

function applyResourceStyles(styles: Record<string, string>) {
  const el = pageUserRef.value
  if (!el) return
  Object.entries(styles).forEach(([k, v]) => el.style.setProperty(k, v))
}

// Watch meta changes → inject CSS variables
watch(() => resourceStore.meta, (meta: ResourceListMeta | null) => {
  if (meta?.styles) {
    applyResourceStyles(meta.styles)
  }
})

async function handleResourceCardClick(id: number) {
  resourceStore.fetchDetail(id, authStore.token || undefined)
  showDetail.value = true
}

function handleDetailDownload(id: number) {
  if (!authStore.isAuthenticated) {
    window.location.href = '/#/login'
    return
  }
  const token = authStore.token
  if (token) {
    resourceStore.getDownloadUrl(id, token).then(url => {
      window.open(url, '_blank')
    })
  }
}

async function switchResourceCategory(catKey: string) {
  resourceStore.setCategory(catKey)
  if (resourceStore.ownedMode) {
    await resourceStore.fetchResources(true, authStore.token || undefined)
  } else {
    await resourceStore.fetchResources()
  }
}

async function loadResources() {
  await resourceStore.fetchResources(false, authStore.token || undefined)
}

onMounted(async () => {
  await loadResources()
})
</script>

<template>
  <div ref="pageUserRef" class="page-user">
    <span v-if="showId" class="cmp-id">{{ componentId }}</span>

    <div style="display:flex; border-bottom:1px solid var(--border); background:var(--bg-secondary); padding:0 16px;">
      <div v-for="tab in tabs" :key="tab.id"
        class="user-tab" :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id">
        <component :is="tab.icon" class="w-4 h-4" />
        <span>{{ t(tab.key) }}</span>
      </div>
    </div>

    <div v-if="activeTab === 'profile'" style="flex:1; overflow:auto; padding:24px;">
      <ProfileTab />
    </div>

    <div v-else-if="activeTab === 'account'" style="flex:1; overflow:auto; padding:24px;">
      <AccountTab @recharge="() => {}" />
    </div>

    <div v-else-if="activeTab === 'order'" style="flex:1; overflow:auto; padding:24px;">
      <OrderTab />
    </div>

    <div v-else-if="activeTab === 'resource'" style="flex:1; overflow:auto; padding:24px;">
      <div style="margin-bottom:16px;">
        <h2 style="font-size:16px; font-weight:600; margin-bottom:4px;">{{ t('settings.resourceCenter', '资源中心') }}</h2>
        <p style="font-size:12px; color:var(--text-muted);">{{ t('settings.resourceCenterDesc', '浏览和下载可导入的结构分析包') }}</p>
      </div>
      <div v-if="resourceStore.meta?.feature_flags?.show_category_filter !== false" style="display:flex; gap:6px; margin-bottom:16px; flex-wrap:wrap; align-items:center;">
        <template v-for="cat in resourceStore.categories" :key="cat.key">
          <button v-if="!cat.auth_required || authStore.isAuthenticated"
            class="btn btn-sm"
            :class="resourceStore.activeCategoryKey === cat.key ? 'btn-primary' : 'btn-ghost'"
            @click="switchResourceCategory(cat.key)">
            {{ cat.label }}
            <span v-if="cat.scope === 'owned' && cat.count !== undefined" style="margin-left:3px; font-size:10px; opacity:0.7;">({{ cat.count }})</span>
          </button>
        </template>
        <div v-if="!authStore.isAuthenticated" style="display:inline-flex; gap:4px; align-items:center;">
          <span style="font-size:11px; color:var(--text-muted);">{{ resourceStore.meta?.labels?.login_hint || '登录后可下载资源' }}</span>
          <router-link to="/login" class="btn btn-primary btn-xs">{{ t('auth.login', '登录') }}</router-link>
        </div>
      </div>
      <div v-if="resourceStore.loading" style="text-align:center; padding:40px; color:var(--text-muted);">{{ t('common.loading') }}...</div>
      <div v-else-if="resourceStore.filteredResources.length === 0" style="text-align:center; padding:40px; color:var(--text-muted);">{{ t('settings.noResources', '暂无资源') }}</div>
      <div v-else style="display:grid; grid-template-columns:repeat(auto-fill,minmax(var(--rc-card-max-w, 220px),1fr)); gap:var(--rc-card-gap, 12px);">
        <ResourceCard v-for="r in resourceStore.filteredResources" :key="r.id"
          :resource="r" :meta="resourceStore.meta || { _version: '0', categories: [], styles: {}, feature_flags: {}, labels: {} }"
          @download="handleResourceCardClick" />
      </div>
    </div>

    <ResourceDetail
      :resource="resourceStore.currentResource"
      :meta="resourceStore.meta"
      :show="showDetail"
      @close="showDetail = false"
      @download="handleDetailDownload" />
  </div>
</template>

<style scoped>
.page-user {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.user-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}
.user-tab:hover { color: var(--text-primary); background: var(--bg-hover); }
.user-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
</style>
