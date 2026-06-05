<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, CheckCircleIcon, XCircleIcon, CloudArrowDownIcon, TrashIcon, MagnifyingGlassIcon } from '@heroicons/vue/24/outline'
import { usePluginStore } from '@/stores/plugin-store'
import { useComponentId } from '@/composables/useComponentId'
import type { ModuleRegistryItemDTO, InstalledModuleDTO } from '@/types/ipc'

const { showId, componentId } = useComponentId('ST-005')
const { t } = useI18n()
const store = usePluginStore()

const activeTab = ref<'local' | 'remote'>('local')
const actionLoading = ref<string | null>(null)
const actionError = ref<string | null>(null)
const successMessage = ref<string | null>(null)

const modules = ref<ModuleRegistryItemDTO[]>([])
const installedModules = ref<Record<string, InstalledModuleDTO>>({})
const loadingModules = ref(false)
const searchQuery = ref('')
const installProgress = ref<string | null>(null)

const filteredModules = computed(() => {
  if (!searchQuery.value) return modules.value
  const q = searchQuery.value.toLowerCase()
  return modules.value.filter(m =>
    m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q) || (m.description ?? '').toLowerCase().includes(q)
  )
})

onMounted(() => {
  store.loadPlugins()
})

async function refreshRemote() {
  loadingModules.value = true
  actionError.value = null
  try {
    const ipc = (window as any).api || (window as any).ipc
    if (!ipc?.module) {
      actionError.value = 'Module API not available (running in browser?)'
      return
    }
    const registry = await ipc.module.listRegistry()
    modules.value = Object.values(registry)
    const installed = await ipc.module.getInstalled()
    installedModules.value = installed
  } catch (e: unknown) {
    actionError.value = (e as Error).message
  } finally {
    loadingModules.value = false
  }
}

async function installModule(id: string) {
  actionLoading.value = id
  actionError.value = null
  successMessage.value = null
  installProgress.value = id
  try {
    const ipc = (window as any).api || (window as any).ipc
    const result = await ipc.module.install(id)
    if (result.success) {
      successMessage.value = `${id} installed`
      await refreshRemote()
    } else {
      actionError.value = `Failed to install ${id}`
    }
  } catch (e: unknown) {
    actionError.value = (e as Error).message
  } finally {
    actionLoading.value = null
    installProgress.value = null
  }
}

async function uninstallModule(id: string) {
  actionLoading.value = id
  actionError.value = null
  successMessage.value = null
  try {
    const ipc = (window as any).api || (window as any).ipc
    const result = await ipc.module.uninstall(id)
    if (result.success) {
      successMessage.value = `${id} uninstalled`
      await refreshRemote()
    } else {
      actionError.value = `Failed to uninstall ${id}`
    }
  } catch (e: unknown) {
    actionError.value = (e as Error).message
  } finally {
    actionLoading.value = null
  }
}

async function updateModule(id: string) {
  actionLoading.value = id
  actionError.value = null
  successMessage.value = null
  installProgress.value = id
  try {
    const ipc = (window as any).api || (window as any).ipc
    const result = await ipc.module.update(id)
    if (result.success) {
      successMessage.value = `${id} updated`
      await refreshRemote()
    } else {
      actionError.value = `Failed to update ${id}`
    }
  } catch (e: unknown) {
    actionError.value = (e as Error).message
  } finally {
    actionLoading.value = null
    installProgress.value = null
  }
}

async function handleLoad(name: string) {
  actionLoading.value = name
  actionError.value = null
  successMessage.value = null
  try {
    await store.loadPlugin(name)
    successMessage.value = `${name} loaded`
  } catch (e: unknown) {
    actionError.value = (e as Error).message
  } finally {
    actionLoading.value = null
  }
}

async function handleUnload(name: string) {
  actionLoading.value = name
  actionError.value = null
  successMessage.value = null
  try {
    await store.unloadPlugin(name)
    successMessage.value = `${name} unloaded`
  } catch (e: unknown) {
    actionError.value = (e as Error).message
  } finally {
    actionLoading.value = null
  }
}

async function handleReload(name: string) {
  actionLoading.value = name
  actionError.value = null
  successMessage.value = null
  try {
    await store.reloadPlugin(name)
    successMessage.value = `${name} reloaded`
  } catch (e: unknown) {
    actionError.value = (e as Error).message
  } finally {
    actionLoading.value = null
  }
}

async function handleInstall(name: string) {
  actionLoading.value = name
  actionError.value = null
  successMessage.value = null
  try {
    await store.installPlugin(name)
    successMessage.value = `${name} deps installed`
  } catch (e: unknown) {
    actionError.value = (e as Error).message
  } finally {
    actionLoading.value = null
  }
}
</script>

<template>
  <div class="module-manager">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>

    <!-- Tabs -->
    <div class="tabs">
      <button
        :class="['tab', { active: activeTab === 'local' }]"
        @click="activeTab = 'local'"
      >
        {{ t('settings.plugins') || 'Local Plugins' }}
      </button>
      <button
        :class="['tab', { active: activeTab === 'remote' }]"
        @click="activeTab = 'remote'"
      >
        Module Store
      </button>
    </div>

    <!-- Alerts -->
    <div
      v-if="actionError"
      class="alert alert-error"
    >
      <XCircleIcon class="w-4 h-4" />
      <span>{{ actionError }}</span>
    </div>
    <div
      v-if="successMessage"
      class="alert alert-success"
    >
      <CheckCircleIcon class="w-4 h-4" />
      <span>{{ successMessage }}</span>
    </div>

    <!-- ==================== Local Plugins Tab ==================== -->
    <div v-if="activeTab === 'local'">
      <div class="header">
        <div>
          <h2>{{ t('settings.plugins') }}</h2>
          <p
            class="text-muted"
            style="font-size:12px;"
          >
            {{ t('settings.pluginsDesc') }}
          </p>
        </div>
        <button
          class="btn btn-ghost btn-sm"
          :disabled="store.loading"
          @click="store.loadPlugins()"
        >
          <ArrowPathIcon
            class="w-4 h-4"
            :class="{ 'animate-spin': store.loading }"
          />
          <span>{{ t('common.refresh') }}</span>
        </button>
      </div>

      <div
        v-if="store.loading && store.pluginList.length === 0"
        class="empty-state"
      >
        <div class="loading-spinner" />
        <span class="text-muted">{{ t('common.loading') }}</span>
      </div>

      <div
        v-else-if="store.pluginList.length === 0"
        class="empty-state"
      >
        <p class="text-muted">
          {{ t('settings.pluginsComingSoon') }}
        </p>
      </div>

      <div
        v-else
        class="plugin-grid"
      >
        <div
          v-for="p in store.pluginList"
          :key="p.name"
          class="plugin-card card"
        >
          <div class="plugin-info">
            <div class="plugin-name">
              <span>{{ p.name }}</span>
              <span class="plugin-version">v{{ p.version }}</span>
            </div>
            <div class="plugin-desc text-muted">
              {{ p.description }}
            </div>
            <div class="plugin-meta">
              <span :class="['badge', p.loaded ? 'badge-green' : 'badge-gray']">
                {{ p.loaded ? 'Loaded' : 'Not Loaded' }}
              </span>
              <span
                v-if="p.platforms?.length"
                class="badge badge-gray"
                style="font-size:9px;"
              >
                {{ p.platforms.join(', ') }}
              </span>
            </div>
          </div>
          <div class="plugin-actions">
            <button
              v-if="!p.loaded"
              class="btn btn-primary btn-sm"
              :disabled="actionLoading === p.name"
              @click="handleLoad(p.name)"
            >
              <span>{{ actionLoading === p.name ? 'Loading...' : 'Load' }}</span>
            </button>
            <button
              v-if="p.loaded"
              class="btn btn-ghost btn-sm"
              :disabled="actionLoading === p.name"
              @click="handleReload(p.name)"
            >
              <ArrowPathIcon
                class="w-3 h-3"
                :class="{ 'animate-spin': actionLoading === p.name }"
              />
              <span>Reload</span>
            </button>
            <button
              v-if="p.loaded"
              class="btn btn-ghost btn-sm"
              style="color:var(--error);"
              :disabled="actionLoading === p.name"
              @click="handleUnload(p.name)"
            >
              <span>Unload</span>
            </button>
            <button
              class="btn btn-ghost btn-sm"
              :disabled="actionLoading === p.name"
              @click="handleInstall(p.name)"
            >
              <span>Deps</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== Remote Module Store Tab ==================== -->
    <div v-if="activeTab === 'remote'">
      <div class="header">
        <div>
          <h2>Module Store</h2>
          <p
            class="text-muted"
            style="font-size:12px;"
          >
            Download and install modules from the registry
          </p>
        </div>
        <button
          class="btn btn-ghost btn-sm"
          :disabled="loadingModules"
          @click="refreshRemote()"
        >
          <ArrowPathIcon
            class="w-4 h-4"
            :class="{ 'animate-spin': loadingModules }"
          />
          <span>Browse</span>
        </button>
      </div>

      <!-- Search -->
      <div
        v-if="modules.length > 0"
        class="search-bar"
      >
        <MagnifyingGlassIcon class="w-4 h-4" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search modules..."
          class="search-input"
        >
      </div>

      <div
        v-if="loadingModules && modules.length === 0"
        class="empty-state"
      >
        <div class="loading-spinner" />
        <span class="text-muted">Loading module registry...</span>
      </div>

      <div
        v-else-if="modules.length === 0 && !loadingModules"
        class="empty-state"
      >
        <CloudArrowDownIcon
          class="w-8 h-8"
          style="color:var(--text-muted);"
        />
        <p class="text-muted">
          Click "Browse" to fetch available modules from the registry
        </p>
      </div>

      <div
        v-else
        class="plugin-grid"
      >
        <div
          v-for="m in filteredModules"
          :key="m.id"
          class="plugin-card card"
        >
          <div class="plugin-info">
            <div class="plugin-name">
              <span>{{ m.name }}</span>
              <span class="plugin-version">v{{ m.version }}</span>
            </div>
            <div class="plugin-desc text-muted">
              {{ m.description }}
            </div>
            <div class="plugin-meta">
              <span :class="['badge', installedModules[m.id] ? 'badge-green' : 'badge-gray']">
                {{ installedModules[m.id] ? `v${installedModules[m.id].version} installed` : 'Not installed' }}
              </span>
              <span
                class="badge badge-gray"
                style="font-size:9px;"
              >
                {{ m.size_kb }} KB
              </span>
              <span
                v-if="m.platforms?.length"
                class="badge badge-gray"
                style="font-size:9px;"
              >
                {{ m.platforms.join(', ') }}
              </span>
            </div>
          </div>
          <div class="plugin-actions">
            <button
              v-if="installedModules[m.id]"
              class="btn btn-primary btn-sm"
              :disabled="actionLoading === m.id"
              @click="updateModule(m.id)"
            >
              <span>{{ actionLoading === m.id ? 'Updating...' : 'Update' }}</span>
            </button>
            <button
              v-if="!installedModules[m.id]"
              class="btn btn-primary btn-sm"
              :disabled="actionLoading === m.id"
              @click="installModule(m.id)"
            >
              <CloudArrowDownIcon class="w-3 h-3" />
              <span>{{ actionLoading === m.id ? 'Installing...' : 'Install' }}</span>
            </button>
            <button
              v-if="installedModules[m.id]"
              class="btn btn-ghost btn-sm"
              style="color:var(--error);"
              :disabled="actionLoading === m.id"
              @click="uninstallModule(m.id)"
            >
              <TrashIcon class="w-3 h-3" />
              <span>Remove</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.module-manager { width: 100%; }

.tabs {
  display: flex;
  gap: 0;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.tab {
  padding: 8px 16px;
  font-size: 13px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.tab.active {
  color: var(--text-primary);
  border-bottom-color: var(--accent);
  font-weight: 600;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.header h2 { font-size: 16px; font-weight: 600; margin-bottom: 4px; }

.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 12px;
}

.search-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  font-size: 13px;
  color: var(--text-primary);
}

.plugin-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plugin-card {
  padding: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.plugin-info { flex: 1; min-width: 0; }

.plugin-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}

.plugin-version {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
}

.plugin-desc { font-size: 11px; margin-bottom: 6px; }

.plugin-meta { display: flex; gap: 6px; flex-wrap: wrap; }

.plugin-actions { display: flex; gap: 4px; flex-shrink: 0; }

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 12px;
}

.alert {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin-bottom: 12px;
}

.alert-error { background: rgba(239,68,68,0.1); color: #ef4444; border: 1px solid rgba(239,68,68,0.2); }
.alert-success { background: rgba(34,197,94,0.1); color: #22c55e; border: 1px solid rgba(34,197,94,0.2); }
</style>
