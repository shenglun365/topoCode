<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  UserIcon,
  ArrowDownTrayIcon,
} from '@heroicons/vue/24/outline'
import { useResourceStore } from '@/stores/resource-store'
import { useAuthStore } from '@/stores/auth-store'
import ProfileTab from '@/components/user/ProfileTab.vue'
import ResourceCard from '@/components/resource/ResourceCard.vue'
import ResourceDetail from '@/components/resource/ResourceDetail.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PG-005')
const { t } = useI18n()
const resourceStore = useResourceStore()
const authStore = useAuthStore()

const activeTab = ref<'profile' | 'resource'>('profile')
const showDetail = ref(false)

const tabs = [
  { id: 'profile' as const, key: 'settings.profile', icon: UserIcon },
  { id: 'resource' as const, key: 'settings.resourceCenter', icon: ArrowDownTrayIcon },
]

async function handleResourceCardClick(id: number) {
  resourceStore.fetchDetail(id)
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

async function switchResourceCategory(cat: string) {
  resourceStore.setCategory(cat)
  await resourceStore.fetchResources()
}

onMounted(async () => {
  await resourceStore.fetchResources()
})
</script>

<template>
  <div class="page-user">
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

    <div v-else-if="activeTab === 'resource'" style="flex:1; overflow:auto; padding:24px;">
      <div style="margin-bottom:16px;">
        <h2 style="font-size:16px; font-weight:600; margin-bottom:4px;">{{ t('settings.resourceCenter', '资源中心') }}</h2>
        <p style="font-size:12px; color:var(--text-muted);">{{ t('settings.resourceCenterDesc', '浏览和下载可导入的结构分析包') }}</p>
      </div>
      <div style="display:flex; gap:6px; margin-bottom:16px; flex-wrap:wrap;">
        <button v-for="cat in resourceStore.categories" :key="cat"
          class="btn btn-sm" :class="resourceStore.activeCategory === cat ? 'btn-primary' : 'btn-ghost'"
          @click="switchResourceCategory(cat)">{{ cat }}</button>
      </div>
      <div v-if="resourceStore.loading" style="text-align:center; padding:40px; color:var(--text-muted);">{{ t('common.loading') }}...</div>
      <div v-else-if="resourceStore.filteredResources.length === 0" style="text-align:center; padding:40px; color:var(--text-muted);">{{ t('settings.noResources', '暂无资源') }}</div>
      <div v-else style="display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px;">
        <ResourceCard v-for="r in resourceStore.filteredResources" :key="r.id"
          :resource="r" @download="handleResourceCardClick" />
      </div>
      <div v-if="!authStore.isAuthenticated" class="login-prompt">
        <span>{{ t('settings.resourceLoginHint', '登录后可下载资源') }}</span>
        <router-link to="/login" class="btn btn-primary btn-sm">{{ t('auth.login', '登录') }}</router-link>
      </div>
    </div>

    <ResourceDetail
      :resource="resourceStore.currentResource"
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
.login-prompt {
  margin-top: 16px; padding: 12px;
  border: 1px solid var(--border); border-radius: 6px;
  display: flex; align-items: center; justify-content: space-between;
  font-size: 12px; color: var(--text-muted);
}
</style>