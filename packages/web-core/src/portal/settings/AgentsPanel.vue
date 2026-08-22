<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ipc } from '../../services/ipc'
import type { AgentConfigItem } from '../../types/ipc'

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
  if (!window.confirm('删除该 Agent 配置？')) return
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
  if (!window.confirm('删除该模板？')) return
  await ipc.promptTemplate.delete({ templateId: id })
  await load()
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <h3>Agent 与模板</h3>

    <div class="section">
      <div class="panel-head">
        <h4>Agent 管理</h4>
        <div class="row">
          <button class="btn btn-ghost btn-xs" @click="detect">检测已安装 Agent</button>
          <button class="btn btn-primary btn-sm" @click="openAddAgent">新增 Agent</button>
        </div>
      </div>
      <table v-if="agents.length" class="settings-table">
        <thead><tr><th>名称</th><th>类型</th><th>使用场景</th><th>状态</th><th>路径</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="a in agents" :key="a.id">
            <td>{{ a.name }}</td>
            <td>{{ a.type }}</td>
            <td>{{ a.scenario || 'general' }}</td>
            <td>{{ a.status }}</td>
            <td class="mono">{{ a.path }}</td>
            <td class="row-actions">
              <button class="btn btn-ghost btn-xs" @click="openEditAgent(a)">编辑</button>
              <button class="btn btn-ghost btn-xs danger" @click="removeAgent(a.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="muted">暂无 Agent 配置。</div>
    </div>

    <div class="section">
      <h4>Prompt 模板</h4>
      <table v-if="templates.length" class="settings-table">
        <thead><tr><th>名称</th><th>模式</th><th>模块</th><th>分类</th><th>语言</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="t in templates" :key="t.id">
            <td>{{ t.name }}</td>
            <td>{{ t.mode }}</td>
            <td>{{ t.module_type || '-' }}</td>
            <td>{{ t.category || '-' }}</td>
            <td>{{ t.locale || '-' }}</td>
            <td class="row-actions">
              <button class="btn btn-ghost btn-xs danger" @click="removeTemplate(t.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="muted">暂无模板。</div>
    </div>

    <div v-if="showAgentForm" class="overlay" @click.self="showAgentForm = false">
      <div class="modal-box">
        <h3>{{ editingAgent ? '编辑 Agent' : '新增 Agent' }}</h3>
        <div class="form-grid">
          <label>名称 <input v-model="agentForm.name" type="text" /></label>
          <label>路径 <input v-model="agentForm.path" type="text" /></label>
          <label>参数 <input v-model="agentForm.args" type="text" /></label>
          <label>使用场景
            <select v-model="agentForm.scenario">
              <option value="">general（通用）</option>
              <option value="chat">AI CHAT</option>
              <option value="workbench">工作台 /app</option>
              <option value="architect">Architect</option>
            </select>
          </label>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showAgentForm = false">取消</button>
          <button class="btn btn-primary" :disabled="!agentForm.name || !agentForm.path" @click="saveAgent">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>
