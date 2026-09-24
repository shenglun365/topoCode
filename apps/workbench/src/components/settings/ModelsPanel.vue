<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ipc } from '@/services/ipc'
import type { ModelConfigItem } from '@/types/ipc'

const { t } = useI18n()

const models = ref<ModelConfigItem[]>([])
const loading = ref(false)
const showForm = ref(false)
const editing = ref<ModelConfigItem | null>(null)
const form = ref({
  id: '', name: '', provider: 'deepseek' as string, model: '', url: '', type: 'cloud',
  temperature: 0.7, maxTokens: 16384, apiKey: '', isDefault: false,
})

async function load() {
  loading.value = true
  try {
    models.value = await ipc.settings.getModels()
  } finally {
    loading.value = false
  }
}

function openAdd() {
  editing.value = null
  form.value = { id: '', name: '', provider: 'deepseek', model: '', url: '', type: 'cloud', temperature: 0.7, maxTokens: 16384, apiKey: '', isDefault: false }
  showForm.value = true
}

function openEdit(m: ModelConfigItem) {
  editing.value = m
  form.value = {
    id: m.id, name: m.name, provider: m.provider, model: m.model, url: m.url, type: m.type || 'cloud',
    temperature: m.temperature ?? 0.7, maxTokens: m.maxTokens ?? 16384, apiKey: m.apiKey || '', isDefault: !!m.isDefault,
  }
  showForm.value = true
}

async function save() {
  if (editing.value) {
    await ipc.settings.updateModel({
      id: form.value.id, name: form.value.name, provider: form.value.provider, model: form.value.model, url: form.value.url,
      temperature: form.value.temperature, maxTokens: form.value.maxTokens, apiKey: form.value.apiKey || undefined, isDefault: form.value.isDefault,
    })
  } else {
    await ipc.settings.addModel({
      name: form.value.name, provider: form.value.provider, model: form.value.model, url: form.value.url, type: form.value.type as any,
      temperature: form.value.temperature, maxTokens: form.value.maxTokens, apiKey: form.value.apiKey || undefined, isDefault: form.value.isDefault,
    })
  }
  showForm.value = false
  await load()
}

async function remove(id: string) {
  if (!window.confirm(t('settings.models.deleteConfirm'))) return
  await ipc.settings.removeModel(id)
  await load()
}

async function setDefault(m: ModelConfigItem) {
  await ipc.settings.updateModel({ id: m.id, isDefault: true })
  await load()
}

async function test(m: ModelConfigItem) {
  try {
    await ipc.settings.testModel(m.id)
    window.alert(t('common.connectionSuccess'))
  } catch (e: any) {
    window.alert(t('settings.models.testFailed', { message: e?.message || String(e) }))
  }
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <div class="panel-head">
      <h3>{{ t('settings.tabs.models') }}</h3>
      <button class="btn btn-primary btn-sm" @click="openAdd">{{ t('settings.models.add') }}</button>
    </div>
    <p class="panel-hint">{{ t('settings.models.hint') }}</p>
    <div v-if="loading" class="empty">{{ t('common.loading') }}</div>
    <table v-else class="settings-table">
      <thead>
        <tr><th>{{ t('common.name') }}</th><th>Provider</th><th>{{ t('settings.models.modelColumn') }}</th><th>{{ t('common.type') }}</th><th>{{ t('common.default') }}</th><th>{{ t('common.status') }}</th><th>{{ t('common.actions') }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="m in models" :key="m.id">
          <td>{{ m.name }}</td>
          <td>{{ m.provider }}</td>
          <td>{{ m.model }}</td>
          <td>{{ m.type }}</td>
          <td>{{ m.isDefault ? '★' : '' }}</td>
          <td>{{ m.status }}</td>
          <td class="row-actions">
            <button class="btn btn-ghost btn-xs" @click="test(m)">{{ t('common.test') }}</button>
            <button v-if="!m.isDefault" class="btn btn-ghost btn-xs" @click="setDefault(m)">{{ t('settings.models.setDefault') }}</button>
            <button class="btn btn-ghost btn-xs" @click="openEdit(m)">{{ t('common.edit') }}</button>
            <button class="btn btn-ghost btn-xs danger" @click="remove(m.id)">{{ t('common.delete') }}</button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <div class="modal-box">
        <h3>{{ editing ? t('settings.models.edit') : t('settings.models.add') }}</h3>
        <div class="form-grid">
          <label>{{ t('common.name') }} <input v-model="form.name" type="text" /></label>
          <label>Provider
            <select v-model="form.provider">
              <option>deepseek</option><option>ollama</option><option>lm-studio</option>
              <option>openrouter</option><option>custom-cloud</option><option>custom-local</option>
            </select>
          </label>
          <label>{{ t('settings.models.modelId') }} <input v-model="form.model" type="text" /></label>
          <label>{{ t('settings.models.apiUrl') }} <input v-model="form.url" type="text" /></label>
          <label>{{ t('common.type') }}
            <select v-model="form.type"><option value="cloud">cloud</option><option value="local">local</option></select>
          </label>
          <label>temperature <input v-model.number="form.temperature" type="number" step="0.1" /></label>
          <label>maxTokens <input v-model.number="form.maxTokens" type="number" /></label>
          <label>API Key <input v-model="form.apiKey" type="password" /></label>
        </div>
        <label class="check"><input v-model="form.isDefault" type="checkbox" /> {{ t('settings.models.setAsDefault') }}</label>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showForm = false">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" :disabled="!form.name || !form.model" @click="save">{{ t('common.save') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
