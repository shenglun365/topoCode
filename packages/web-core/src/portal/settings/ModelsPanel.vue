<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ipc } from '../../services/ipc'
import type { ModelConfigItem } from '../../types/ipc'

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
  if (!window.confirm('删除该模型配置？')) return
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
    window.alert('连接成功')
  } catch (e: any) {
    window.alert(`连接失败: ${e?.message || String(e)}`)
  }
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <div class="panel-head">
      <h3>模型设置</h3>
      <button class="btn btn-primary btn-sm" @click="openAdd">新增模型</button>
    </div>
    <p class="panel-hint">共享模型库（model_configs），各子模块可独立选择与上下文容量。</p>
    <div v-if="loading" class="empty">加载中...</div>
    <table v-else class="settings-table">
      <thead>
        <tr><th>名称</th><th>Provider</th><th>模型</th><th>类型</th><th>默认</th><th>状态</th><th>操作</th></tr>
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
            <button class="btn btn-ghost btn-xs" @click="test(m)">测试</button>
            <button v-if="!m.isDefault" class="btn btn-ghost btn-xs" @click="setDefault(m)">设默认</button>
            <button class="btn btn-ghost btn-xs" @click="openEdit(m)">编辑</button>
            <button class="btn btn-ghost btn-xs danger" @click="remove(m.id)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <div class="modal-box">
        <h3>{{ editing ? '编辑模型' : '新增模型' }}</h3>
        <div class="form-grid">
          <label>名称 <input v-model="form.name" type="text" /></label>
          <label>Provider
            <select v-model="form.provider">
              <option>deepseek</option><option>ollama</option><option>lm-studio</option>
              <option>openrouter</option><option>custom-cloud</option><option>custom-local</option>
            </select>
          </label>
          <label>模型标识 <input v-model="form.model" type="text" /></label>
          <label>API 地址 <input v-model="form.url" type="text" /></label>
          <label>类型
            <select v-model="form.type"><option value="cloud">cloud</option><option value="local">local</option></select>
          </label>
          <label>temperature <input v-model.number="form.temperature" type="number" step="0.1" /></label>
          <label>maxTokens <input v-model.number="form.maxTokens" type="number" /></label>
          <label>API Key <input v-model="form.apiKey" type="password" /></label>
        </div>
        <label class="check"><input v-model="form.isDefault" type="checkbox" /> 设为默认模型</label>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showForm = false">取消</button>
          <button class="btn btn-primary" :disabled="!form.name || !form.model" @click="save">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>
