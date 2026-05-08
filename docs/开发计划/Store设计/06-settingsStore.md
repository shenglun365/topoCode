# stores/settings.ts

> Phase 5: 系统设置状态管理

```typescript
import { defineStore } from 'pinia';

interface ModelConfig {
  id: string;
  name: string;
  type: 'ollama' | 'openai' | 'custom';
  model: string;
  endpoint: string;
  apiKey?: string;
  isDefault: boolean;
  status: 'online' | 'offline' | 'error';
  temperature?: number;
  maxTokens?: number;
}

interface TaskModelBinding {
  taskType: 'syntax' | 'function' | 'qa';
  modelId: string;
}

interface ModelUsageLimit {
  modelId: string;
  monthlyLimit: number;
  currentUsage: number;
}

interface AgentConfig {
  id: string;
  name: string;
  path: string;
  args: string[];
  isDefault: boolean;
  status: 'available' | 'not-found' | 'error';
}

interface SkillConfig {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
}

interface PluginConfig {
  id: string;
  name: string;
  icon: string;
  version: string;
  status: 'loaded' | 'loading' | 'not-installed' | 'error';
  enabled: boolean;
}

interface GeneralSettings {
  theme: 'dark' | 'light' | 'system';
  language: 'zh' | 'en';
  fontSize: number;
  autoSaveInterval: number;
  httpServer: {
    enabled: boolean;
    port: number;
  };
}

interface AppInfo {
  version: string;
  buildNumber: string;
  electronVersion: string;
  nodeVersion: string;
  pythonVersion: string;
  updateStatus: 'checking' | 'up-to-date' | 'available' | 'error';
}

export const useSettingsStore = defineStore('settings', () => {
  // ---- State ----
  const activeTab = ref<string>('ai');

  // 模型配置
  const models = ref<ModelConfig[]>([]);
  const taskBindings = ref<TaskModelBinding[]>([]);
  const usageLimits = ref<ModelUsageLimit[]>([]);
  const modelPriority = ref<string[]>([]);  // 按优先级排序的 modelId 数组

  // Agent 配置
  const agents = ref<AgentConfig[]>([]);

  // SKILL 配置
  const skills = ref<SkillConfig[]>([]);

  // 插件
  const plugins = ref<PluginConfig[]>([]);

  // 通用设置
  const general = ref<GeneralSettings>({
    theme: 'dark',
    language: 'zh',
    fontSize: 13,
    autoSaveInterval: 60,
    httpServer: { enabled: false, port: 8080 },
  });

  // 关于
  const appInfo = ref<AppInfo>({
    version: '0.1.0',
    buildNumber: '',
    electronVersion: '',
    nodeVersion: '',
    pythonVersion: '',
    updateStatus: 'up-to-date',
  });

  // ---- Getters ----
  const defaultModel = computed(() =>
    models.value.find(m => m.isDefault) ?? null
  );

  const onlineModels = computed(() =>
    models.value.filter(m => m.status === 'online')
  );

  const defaultAgent = computed(() =>
    agents.value.find(a => a.isDefault) ?? null
  );

  const enabledSkills = computed(() =>
    skills.value.filter(s => s.enabled)
  );

  // ---- Actions ----
  function setActiveTab(tab: string) {
    activeTab.value = tab;
  }

  // 模型操作
  function setModels(list: ModelConfig[]) { models.value = list; }
  function addModel(model: ModelConfig) { models.value.push(model); }
  function updateModel(id: string, updates: Partial<ModelConfig>) {
    const idx = models.value.findIndex(m => m.id === id);
    if (idx !== -1) Object.assign(models.value[idx], updates);
  }
  function deleteModel(id: string) {
    models.value = models.value.filter(m => m.id !== id);
  }
  function setDefaultModel(id: string) {
    models.value.forEach(m => (m.isDefault = m.id === id));
  }

  // 任务绑定
  function setTaskBindings(bindings: TaskModelBinding[]) { taskBindings.value = bindings; }

  // 用量限制
  function setUsageLimits(limits: ModelUsageLimit[]) { usageLimits.value = limits; }

  // 模型优先级
  function setModelPriority(ids: string[]) { modelPriority.value = ids; }

  // Agent 操作
  function setAgents(list: AgentConfig[]) { agents.value = list; }

  // SKILL 操作
  function setSkills(list: SkillConfig[]) { skills.value = list; }
  function toggleSkill(id: string) {
    const skill = skills.value.find(s => s.id === id);
    if (skill) skill.enabled = !skill.enabled;
  }

  // 插件操作
  function setPlugins(list: PluginConfig[]) { plugins.value = list; }

  // 通用设置
  function updateGeneral(updates: Partial<GeneralSettings>) {
    Object.assign(general.value, updates);
  }

  // App 信息
  function setAppInfo(info: Partial<AppInfo>) {
    Object.assign(appInfo.value, info);
  }

  return {
    activeTab,
    models, taskBindings, usageLimits, modelPriority,
    agents, skills, plugins, general, appInfo,
    defaultModel, onlineModels, defaultAgent, enabledSkills,
    setActiveTab,
    setModels, addModel, updateModel, deleteModel, setDefaultModel,
    setTaskBindings, setUsageLimits, setModelPriority,
    setAgents,
    setSkills, toggleSkill,
    setPlugins,
    updateGeneral,
    setAppInfo,
  };
});
```
