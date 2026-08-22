<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  UserIcon,
  ArrowDownTrayIcon,
  CurrencyDollarIcon,
  DocumentTextIcon,
} from '@heroicons/vue/24/outline'
import { AppToolbar, readFontSize, setFontSize } from '../../shell'
import type { FontSizeTarget } from '../../shell'
import { useResource } from './use-resource'
import { useAuth } from './use-auth'
import { resourceService } from './resource-service'
import { API_BASE } from '../../utils/http'
import ProfileTab from './ProfileTab.vue'
import AccountTab from './AccountTab.vue'
import OrderTab from './OrderTab.vue'
import ResourceCard from './ResourceCard.vue'
import ResourceDetail from './ResourceDetail.vue'
import type { ResourceListMeta } from './types'

const { t, locale } = useI18n()
const resourceStore = useResource()
const auth = useAuth()

const FONT_TARGETS: FontSizeTarget[] = ['--content-font-size']
const fontSize = ref(readFontSize())

function onFontSize(v: number) {
  fontSize.value = v
  setFontSize(v, FONT_TARGETS)
}

function onLocale(l: string) {
  locale.value = l
}

const activeTab = ref<'profile' | 'account' | 'order' | 'resource'>('profile')
const showDetail = ref(false)
const pageUserRef = ref<HTMLElement | null>(null)
const downloadError = ref('')
const downloadLimitDialog = ref(false)
const downloadLimitMsg = ref('')

// 自动导入状态
const importing = ref(false)
const importProgress = ref(0)
const importMessage = ref('')
const importDone = ref(false)
const newProjectId = ref('')
const newProjectName = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

let errorTimer: ReturnType<typeof setTimeout> | null = null
function showError(msg: string) {
  downloadError.value = msg
  if (errorTimer) clearTimeout(errorTimer)
  errorTimer = setTimeout(() => { downloadError.value = '' }, 4000)
}
function showDownloadLimitDialog(msg: string) {
  downloadLimitMsg.value = msg
  downloadLimitDialog.value = true
}

async function autoDownloadAndImport(resourceId: number) {
  importing.value = true
  importProgress.value = 0
  importMessage.value = t('resource.import.gettingUrl')
  importDone.value = false
  try {
    // 1. 获取下载信息
    const info = await resourceService.getDownloadInfo(resourceId)
    const url = info.oss_url || `${API_BASE}${info.redirect_url}`
    const api = (window as any).api
    if (api?.fs?.downloadUrl && api?.call) {
      // Electron：本地下载并导入为工作台项目
      importMessage.value = t('resource.import.downloading')
      const filePath = await api.fs.downloadUrl(url)
      importMessage.value = t('resource.import.importing')
      importProgress.value = 50
      const detail = resourceStore.currentResource
      const result = await api.call('resource.importProject', {
        archivePath: filePath,
        resourceId: String(resourceId),
        name: detail?.title || `${t('resource.center')} #${resourceId}`,
        resourceProjectsDir: localStorage.getItem('resourceProjectsDir') || '',
      })
      startPollingImport(result.importId)
      return
    }
    // Web：浏览器直接下载资源包
    window.open(url, '_blank')
    importing.value = false
  } catch (err: any) {
    importing.value = false
    const msg = err.message || t('resource.import.downloadFailed')
    if (msg.includes(t('resource.import.downloadLimitReached')) || msg.includes(t('resource.import.contactSupport'))) {
      showDownloadLimitDialog(msg)
    } else {
      showError(msg)
    }
  }
}

function startPollingImport(importId: string) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const status = await (window as any).api.system.importStatus(importId)
      if (!status) return
      importProgress.value = status.progress || 0
      importMessage.value = status.message || ''
      if (status.status === 'done') {
        if (pollTimer) clearInterval(pollTimer)
        importing.value = false
        importDone.value = false
        showDetail.value = false
        newProjectId.value = status.result?.projectId || ''
        newProjectName.value = status.result?.projectName || ''
        setTimeout(() => {
          if (newProjectId.value) {
            window.location.href = `/app/#/code?project=${newProjectId.value}`
          }
        }, 500)
      } else if (status.status === 'error') {
        if (pollTimer) clearInterval(pollTimer)
        importing.value = false
        showError(status.message || t('resource.import.importFailed'))
      }
    } catch { /* ignore */ }
  }, 10000)
}

// 登录过期自动切到个人资料页（显示登录提示）
watch(() => auth.authExpired, (val) => {
  if (val) {
    activeTab.value = 'profile'
  }
})

function closeImportDialog() {
  if (pollTimer) clearInterval(pollTimer)
  importing.value = false
  importDone.value = false
}

const tabs = [
  { id: 'profile' as const, key: 'settings.profile', icon: UserIcon },
  { id: 'account' as const, key: 'auth.account', icon: CurrencyDollarIcon },
  { id: 'order' as const, key: 'auth.order', icon: DocumentTextIcon },
  { id: 'resource' as const, key: 'resource.center', icon: ArrowDownTrayIcon },
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
  showDetail.value = true
  try {
    await resourceStore.fetchDetail(id, auth.token || undefined)
  } catch {
    showDetail.value = false
    showError(t('resource.error.notFound'))
  }
}

function handleDetailDownload(id: number) {
  if (!auth.isAuthenticated) {
    window.location.href = '/app/#/login'
    return
  }
  autoDownloadAndImport(id)
}

const ESSENTIAL_KEYS = ['', '__prerelease__', '__free__', '__points__', '已购']
const CATEGORY_LABEL_KEYS: Record<string, string> = {
  '': 'resource.categoryAll',
  '__prerelease__': 'resource.categoryPrerelease',
  '__free__': 'resource.categoryFree',
  '__points__': 'resource.categoryPoints',
  '已购': 'resource.owned',
}
function catLabel(cat: { key: string; label: string }): string {
  const i18nKey = CATEGORY_LABEL_KEYS[cat.key]
  return i18nKey ? t(i18nKey) : cat.label
}

function refreshResources() {
  resourceStore.fetchResources(resourceStore.ownedMode, auth.token || undefined)
}

let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput(e: Event) {
  const value = (e.target as HTMLInputElement).value
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    resourceStore.setSearch(value)
    doFetch()
  }, 600)
}

function onSortChange(by: string, order: string) {
  resourceStore.setSort(by, order)
  doFetch()
}

function doFetch() {
  if (resourceStore.ownedMode) {
    resourceStore.fetchResources(true, auth.token || undefined)
  } else {
    resourceStore.fetchResources()
  }
}

async function switchResourceCategory(catKey: string) {
  resourceStore.setCategory(catKey)
  if (resourceStore.ownedMode) {
    await resourceStore.fetchResources(true, auth.token || undefined)
  } else {
    await resourceStore.fetchResources()
  }
}

async function loadResources() {
  await resourceStore.fetchResources(false, auth.token || undefined)
}

onMounted(async () => {
  await loadResources()
})
</script>

<template>
  <div
    ref="pageUserRef"
    class="page-user"
  >
    <AppToolbar
      app-key="portal"
      :title="t('nav.userCenter')"
      :font-size="fontSize"
      :font-targets="FONT_TARGETS"
      @update:font-size="onFontSize"
      @update:locale="onLocale"
    >
      <template #tools>
        <a
          href="#/"
          class="toolbar-btn"
        >← {{ t('nav.backHome', '返回首页') }}</a>
        <a
          href="#/settings"
          class="toolbar-btn"
        >{{ t('nav.settings') }}</a>
      </template>
    </AppToolbar>

    <div class="user-body">
      <aside class="user-nav">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="user-nav-item"
          :class="{ active: activeTab === tab.id }"
          @click="activeTab = tab.id"
        >
          <component
            :is="tab.icon"
            class="w-4 h-4"
          />
          <span>{{ t(tab.key) }}</span>
        </button>
      </aside>

      <main class="user-main">
        <div
          v-if="auth.authExpired"
          class="auth-expired-banner"
        >
          <svg
            class="banner-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle
              cx="12"
              cy="12"
              r="10"
            />
            <path d="M12 8v4" />
            <path d="M12 16h.01" />
          </svg>
          <span class="banner-text">{{ t('auth.sessionExpired', '登录已过期，请重新登录') }}</span>
          <a
            href="/app/#/login"
            class="btn btn-primary btn-xs"
            style="flex-shrink:0;"
          >
            {{ t('auth.login', '登录') }}
          </a>
          <button
            class="btn btn-ghost btn-icon btn-xs"
            style="flex-shrink:0;"
            @click="auth.authExpired = false"
          >
            ✕
          </button>
        </div>

        <div
          v-if="activeTab === 'profile'"
          class="tab-pane"
        >
          <ProfileTab />
        </div>

        <div
          v-else-if="activeTab === 'account'"
          class="tab-pane"
        >
          <AccountTab @recharge="() => {}" />
        </div>

        <div
          v-else-if="activeTab === 'order'"
          class="tab-pane"
        >
          <OrderTab />
        </div>

        <div
          v-else-if="activeTab === 'resource'"
          class="tab-pane"
        >
          <div style="margin-bottom:16px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <h2 style="font-size:16px; font-weight:600;">
                {{ t('resource.center', '资源中心') }}
              </h2>
              <button
                class="btn btn-ghost btn-icon btn-xs"
                :disabled="resourceStore.loading"
                :title="t('common.refresh')"
                @click="refreshResources"
              >
                <svg
                  class="icon-refresh"
                  :class="{ spinning: resourceStore.loading }"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                ><path d="M21 2v6h-6" /><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M3 22v-6h6" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /></svg>
              </button>
            </div>
            <p style="font-size:12px; color:var(--text-muted); margin-top:4px;">
              {{ t('resource.centerDesc', '浏览和下载可导入的结构分析包') }}
            </p>
          </div>
          <div style="display:flex; gap:8px; margin-bottom:12px; align-items:center; flex-wrap:wrap;">
            <div class="search-wrap">
              <svg
                class="search-icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              ><circle
                cx="11"
                cy="11"
                r="8"
              /><path d="m21 21-4.35-4.35" /></svg>
              <input
                class="search-input"
                type="text"
                :placeholder="t('resource.search', '搜索资源')"
                @input="onSearchInput"
              >
            </div>
            <select
              class="sort-select"
              :value="resourceStore.sortBy"
              @change="onSortChange(($event.target as HTMLSelectElement).value, resourceStore.sortOrder)"
            >
              <option value="time">
                {{ t('settings.sortByTime', '时间') }}
              </option>
              <option value="name">
                {{ t('settings.sortByName', '名称') }}
              </option>
              <option value="downloads">
                {{ t('settings.sortByDownloads', '下载量') }}
              </option>
            </select>
            <select
              class="sort-select"
              :value="resourceStore.sortOrder"
              @change="onSortChange(resourceStore.sortBy, ($event.target as HTMLSelectElement).value)"
            >
              <option value="desc">
                {{ t('settings.sortDesc', '倒序') }}
              </option>
              <option value="asc">
                {{ t('settings.sortAsc', '正序') }}
              </option>
            </select>
          </div>
          <div
            v-if="resourceStore.meta?.feature_flags?.show_category_filter !== false"
            style="display:flex; gap:6px; margin-bottom:16px; flex-wrap:wrap; align-items:center;"
          >
            <button
              v-for="key in ESSENTIAL_KEYS"
              :key="key"
              class="btn btn-sm"
              :class="resourceStore.activeCategoryKey === key ? 'btn-primary' : 'btn-ghost'"
              @click="switchResourceCategory(key)"
            >
              {{ catLabel({ key, label: '' }) }}
            </button>
            <template
              v-for="cat in resourceStore.categories"
              :key="'xtra-' + cat.key"
            >
              <button
                v-if="!ESSENTIAL_KEYS.includes(cat.key)"
                class="btn btn-sm"
                :class="resourceStore.activeCategoryKey === cat.key ? 'btn-primary' : 'btn-ghost'"
                @click="switchResourceCategory(cat.key)"
              >
                {{ cat.label }}
                <span
                  v-if="cat.count !== undefined"
                  style="margin-left:3px; font-size:10px; opacity:0.7;"
                >({{ cat.count }})</span>
              </button>
            </template>
            <div
              v-if="!auth.isAuthenticated"
              style="display:inline-flex; gap:4px; align-items:center;"
            >
              <span style="font-size:11px; color:var(--text-muted);">{{ resourceStore.meta?.labels?.login_hint || '登录后可下载资源' }}</span>
              <a
                href="/app/#/login"
                class="btn btn-primary btn-xs"
              >
                {{ t('auth.login', '登录') }}
              </a>
            </div>
          </div>
          <div
            v-if="resourceStore.loading"
            style="text-align:center; padding:40px; color:var(--text-muted);"
          >
            {{ t('common.loading') }}...
          </div>
          <div
            v-else-if="resourceStore.filteredResources.length === 0"
            style="text-align:center; padding:40px; color:var(--text-muted);"
          >
            {{ t('resource.noResources', '暂无资源') }}
          </div>
          <div
            v-else
            style="display:grid; grid-template-columns:repeat(auto-fill,minmax(var(--rc-card-max-w, 220px),1fr)); gap:var(--rc-card-gap, 12px);"
          >
            <ResourceCard
              v-for="r in resourceStore.filteredResources"
              :key="r.id"
              :resource="r"
              :meta="resourceStore.meta || { _version: '0', categories: [], styles: {}, feature_flags: {}, labels: {} }"
              @download="handleResourceCardClick"
            />
          </div>
        </div>
      </main>
    </div>

    <ResourceDetail
      :resource="resourceStore.currentResource"
      :meta="resourceStore.meta"
      :show="showDetail"
      @close="showDetail = false"
      @download="handleDetailDownload"
    />

    <Teleport to="body">
      <div
        v-if="downloadError"
        class="toast"
      >
        {{ downloadError }}
      </div>
    </Teleport>

    <!-- 下载次数上限弹窗 -->
    <Teleport to="body">
      <div
        v-if="downloadLimitDialog"
        class="dialog-overlay"
        @click.self="downloadLimitDialog = false"
      >
        <div class="limit-dialog">
          <div class="limit-dialog-icon">
            ⚠️
          </div>
          <div class="limit-dialog-title">
            {{ t('resource.import.downloadLimitReached') }}
          </div>
          <div class="limit-dialog-msg">
            {{ downloadLimitMsg }}
          </div>
          <div class="limit-dialog-actions">
            <button
              class="btn btn-primary btn-sm"
              @click="downloadLimitDialog = false"
            >
              {{ t('common.gotIt') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 自动导入进度弹窗 -->
    <Teleport to="body">
      <div
        v-if="importing || importDone"
        class="dialog-overlay"
      >
        <div class="import-dialog">
          <div v-if="!importDone">
            <div class="import-spinner" />
            <div class="import-title">
              {{ t('resource.import.importingResource') }}
            </div>
            <div class="import-progress-bar">
              <div
                class="import-progress-fill"
                :style="{ width: importProgress + '%' }"
              />
            </div>
            <div class="import-msg">
              {{ importMessage }}
            </div>
          </div>
          <div v-else>
            <div class="import-done-icon">
              ✓
            </div>
            <div class="import-title">
              {{ t('resource.import.completed') }}
            </div>
            <div class="import-msg">
              {{ newProjectName }}
            </div>
            <div class="import-actions">
              <button
                class="btn btn-primary btn-sm"
                @click="closeImportDialog"
              >
                {{ t('common.close') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.page-user {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-primary);
  color: var(--text-primary);
}
.user-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.user-nav {
  width: calc(180px * var(--ui-scale));
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  padding: calc(12px * var(--ui-scale)) 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--bg-secondary);
}
.user-nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px calc(12px * var(--ui-scale));
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
  font-size: calc(13px * var(--ui-scale));
}
.user-nav-item svg {
  width: calc(16px * var(--ui-scale));
  height: calc(16px * var(--ui-scale));
  flex-shrink: 0;
}
.user-nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.user-nav-item.active {
  background: var(--bg-tertiary);
  color: var(--accent);
  font-weight: 600;
}
.user-main {
  flex: 1;
  overflow: auto;
  padding: calc(20px * var(--ui-scale)) calc(24px * var(--ui-scale));
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.tab-pane {
  flex: 1;
  min-height: 0;
}
.icon-refresh { width: calc(16px * var(--ui-scale)); height: calc(16px * var(--ui-scale)); }
.icon-refresh.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.toast {
  position: fixed; bottom: 40px; left: 50%; transform: translateX(-50%);
  padding: 8px calc(20px * var(--ui-scale));
  border-radius: 6px; font-size: calc(12px * var(--ui-scale)); z-index: 99999;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
.dialog-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.55);
  display: flex; align-items: center; justify-content: center; z-index: 10000;
}
.import-dialog {
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: 10px; padding: calc(28px * var(--ui-scale)) calc(32px * var(--ui-scale)); max-width: calc(360px * var(--ui-scale)); width: 90vw;
  text-align: center;
}
.import-spinner {
  width: calc(28px * var(--ui-scale));
  border: 3px solid var(--border); border-top-color: var(--accent);
  border-radius: 50%; animation: import-spin 0.8s linear infinite;
}
@keyframes import-spin { to { transform: rotate(360deg); } }
.import-done-icon {
  width: calc(40px * var(--ui-scale));
  background: var(--success); color: #fff; font-size: calc(20px * var(--ui-scale)); font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.import-title { font-size: calc(15px * var(--ui-scale)); font-weight: 600; color: var(--text-primary); margin-bottom: calc(12px * var(--ui-scale)); }
.import-progress-bar { height: 6px; background: var(--bg-tertiary); border-radius: 3px; overflow: hidden; margin-bottom: 8px; }
.import-progress-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.import-msg { font-size: calc(12px * var(--ui-scale)); color: var(--text-muted); margin-bottom: calc(12px * var(--ui-scale)); }
.import-actions { display: flex; justify-content: center; gap: 6px; }
.limit-dialog {
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: 10px; padding: calc(24px * var(--ui-scale)); max-width: calc(380px * var(--ui-scale)); width: 90vw;
  text-align: center;
}
.limit-dialog-icon { font-size: calc(32px * var(--ui-scale)); margin-bottom: 8px; }
.limit-dialog-title { font-size: calc(15px * var(--ui-scale)); font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.limit-dialog-msg { font-size: calc(12px * var(--ui-scale)); color: var(--text-muted); line-height: 1.6; margin-bottom: calc(16px * var(--ui-scale)); }
.limit-dialog-actions { display: flex; justify-content: center; }
.search-wrap {
  position: relative; display: flex; align-items: center;
}
.search-icon {
  position: absolute; left: 8px; width: calc(14px * var(--ui-scale)); height: calc(14px * var(--ui-scale));
  color: var(--text-muted); pointer-events: none;
}
.search-input {
  padding: 6px 8px 6px calc(28px * var(--ui-scale));
  border-radius: 6px; background: var(--bg-primary);
  color: var(--text-primary); font-size: calc(12px * var(--ui-scale)); width: calc(200px * var(--ui-scale));
  outline: none;
}
.search-input:focus { border-color: var(--accent); }
.search-input::placeholder { color: var(--text-muted); }
.sort-select {
  padding: 6px 8px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--bg-primary);
  color: var(--text-primary); font-size: calc(12px * var(--ui-scale)); outline: none; cursor: pointer;
}
.sort-select:focus { border-color: var(--accent); }
.auth-expired-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: calc(10px * var(--ui-scale)) calc(16px * var(--ui-scale));
  margin: 0 0 calc(16px * var(--ui-scale));
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid var(--error);
  border-radius: 8px;
  flex-shrink: 0;
}
.banner-icon {
  width: calc(18px * var(--ui-scale));
  height: calc(18px * var(--ui-scale));
  color: var(--error);
  flex-shrink: 0;
}
.banner-text {
  flex: 1;
  font-size: calc(13px * var(--ui-scale));
  color: var(--error);
}
</style>
