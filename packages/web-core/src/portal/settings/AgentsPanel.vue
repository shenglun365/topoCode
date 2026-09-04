<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ipc } from '../../services/ipc'
import type { AgentConfigItem } from '../../types/ipc'

const { t } = useI18n()

const agents = ref<AgentConfigItem[]>([])
const templates = ref<Array<{ id: string; name: string; mode: string; category: string | null; module_type: string | null; locale: string | null }>>([])
const showAgentForm = ref(false)
const agentForm = ref({ id: '', name: '', path: '', args: '', type: 'cli', scenario: '' })
const editingAgent = ref<AgentConfigItem | null>(null)

const SCENARIOS = ['chat', 'workbench', 'architect', 'general']

async function load() {
  try {
    agents.value = await ipc.settings.getAgents()
  } catch (e) {
    console.warn('[AgentsPanel] load agents failed:', e)
  }
  try {
    const data = await ipc.promptTemplate.list({})
    templates.value = data.templates
  } catch (e) {
    console.warn('[AgentsPanel] load templates failed:', e)
  }
}

function openAddAgent() {
  editingAgent.value = null
  agentForm.value = { id: '', name: '', path: '', args: '', type: 'cli', scenario: '' }
  showAgentForm.value = true
}

function openEditAgent(a: AgentConfigItem) {
  editingAgent.value = a
  agentForm.value = { id: a.id, name: a.name, path: a.path, args: a.args, type: a.type || 'cli', scenario: a.scenario || '' }
  showAgentForm.value = true
}

async function saveAgent() {
  if (editingAgent.value) {
    await ipc.settings.updateAgent({ id: agentForm.value.id, name: agentForm.value.name, path: agentForm.value.path, args: agentForm.value.args, scenario: agentForm.value.scenario })
  } else {
    await ipc.settings.addAgent({ name: agentForm.value.name, path: agentForm.value.path, args: agentForm.value.args, type: agentForm.value.type, scenario: agentForm.value.scenario })
  }
  showAgentForm.value = false
  await load()
}

async function removeAgent(id: string) {
  if (!window.confirm(t('settings.agents.deleteConfirm'))) return
  await ipc.settings.removeAgent(id)
  await load()
}

async function detect() {
  try {
    await ipc.settings.detectAgent('')
    await load()
  } catch (e) {
    console.warn('[AgentsPanel] detect failed:', e)
  }
}

async function removeTemplate(id: string) {
  if (!window.confirm(t('settings.templates.deleteConfirm'))) return
  await ipc.promptTemplate.delete({ templateId: id })
  await load()
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <h3>{{ t('settings.tabs.agents') }}</h3>

    <div class="section">
      <div class="panel-head">
        <h4>{{ t('settings.agents.management') }}</h4>
        <div class="row">
          <button class="btn btn-ghost btn-xs" @click="detect">{{ t('settings.agents.detect') }}</button>
          <button class="btn btn-primary btn-sm" @click="openAddAgent">{{ t('settings.agents.add') }}</button>
        </div>
      </div>
      <table v-if="agents.length" class="settings-table">
        <thead><tr><th>{{ t('common.name') }}</th><th>{{ t('common.type') }}</th><th>{{ t('settings.agents.scenario') }}</th><th>{{ t('common.status') }}</th><th>{{ t('common.path') }}</th><th>{{ t('common.actions') }}</th></tr></thead>
        <tbody>
          <tr v-for="a in agents" :key="a.id">
            <td>{{ a.name }}</td>
            <td>{{ a.type }}</td>
            <td>{{ a.scenario || 'general' }}</td>
            <td>{{ a.status }}</td>
            <td class="mono">{{ a.path }}</td>
            <td class="row-actions">
              <button class="btn btn-ghost btn-xs" @click="openEditAgent(a)">{{ t('common.edit') }}</button>
              <button class="btn btn-ghost btn-xs danger" @click="removeAgent(a.id)">{{ t('common.delete') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="muted">{{ t('settings.agents.empty') }}</div>
    </div>

    <div class="section">
      <h4>{{ t('settings.templates.title') }}</h4>
      <table v-if="templates.length" class="settings-table">
        <thead><tr><th>{{ t('common.name') }}</th><th>{{ t('settings.templates.mode') }}</th><th>{{ t('settings.templates.module') }}</th><th>{{ t('common.category') }}</th><th>{{ t('settings.templates.language') }}</th><th>{{ t('common.actions') }}</th></tr></thead>
        <tbody>
          <tr v-for="t2 in templates" :key="t2.id">
            <td>{{ t2.name }}</td>
            <td>{{ t2.mode }}</td>
            <td>{{ t2.module_type || '-' }}</td>
            <td>{{ t2.category || '-' }}</td>
            <td>{{ t2.locale || '-' }}</td>
            <td class="row-actions">
              <button class="btn btn-ghost btn-xs danger" @click="removeTemplate(t2.id)">{{ t('common.delete') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="muted">{{ t('settings.templates.empty') }}</div>
    </div>

    <div v-if="showAgentForm" class="overlay" @click.self="showAgentForm = false">
      <div class="modal-box">
        <h3>{{ editingAgent ? t('settings.agents.edit') : t('settings.agents.add') }}</h3>
        <div class="form-grid">
          <label>{{ t('common.name') }} <input v-model="agentForm.name" type="text" /></label>
          <label>{{ t('common.path') }} <input v-model="agentForm.path" type="text" /></label>
          <label>{{ t('settings.agents.args') }} <input v-model="agentForm.args" type="text" /></label>
          <label>{{ t('settings.agents.scenario') }}
            <select v-model="agentForm.scenario">
              <option value="">{{ t('settings.agents.scenarioGeneral') }}</option>
              <option value="chat">AI CHAT</option>
              <option value="workbench">{{ t('settings.appNames.workbench') }}</option>
              <option value="architect">Architect</option>
            </select>
          </label>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showAgentForm = false">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" :disabled="!agentForm.name || !agentForm.path" @click="saveAgent">{{ t('common.save') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
