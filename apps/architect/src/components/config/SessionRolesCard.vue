<script setup lang="ts">
/**
 * 会话执行角色管理（PR2 角色体系）。
 *
 * 数据面：主库 arch_session_roles（GET/PUT /session-roles, DELETE /session-roles/{id}）。
 * - architect：系统种子角色，唯一/不可删/绑定不可改；新会话默认角色。
 * - executor：多个，各绑一个执行器实例（agent.executors 条目），模型从实例内
 *   models 列表选择（模型完全下沉进实例）。
 * 删除保护：被未归档会话引用的角色不可删（后端校验，前端提示）。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { UserGroupIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { apiGet, apiPut, apiDelete } from '@/services/api-client'

interface ExecModel { id: string; name: string; model: string }
interface ExecEntry { id: string; type: string; host: string; config: Record<string, any> & { models?: ExecModel[] } }
interface SessionRole {
  id: string
  name: string
  kind: 'architect' | 'executor' | string
  executorId: string
  modelId: string
  skills: string[]
  tools: string[]
  permissions: Record<string, any>
  builtin?: boolean
  executorLabel?: string
  skillPool?: string[]
}

const { t } = useI18n()
const roles = ref<SessionRole[]>([])
const executors = ref<ExecEntry[]>([])
const loading = ref(false)
const msg = ref('')
const savingId = ref('')

async function load() {
  loading.value = true
  try {
    const [r, e] = await Promise.all([
      apiGet<SessionRole[]>('/session-roles'),
      apiGet<{ executors: ExecEntry[] }>('/agent/executors'),
    ])
    roles.value = r ?? []
    executors.value = (e.executors ?? []).filter((x) => x.id !== 'architect')
  } catch {
    roles.value = []
  } finally {
    loading.value = false
  }
}
onMounted(load)

function execModels(role: SessionRole): ExecModel[] {
  const ex = executors.value.find((x) => x.id === role.executorId)
  return ex?.config?.models ?? []
}

function addRole() {
  roles.value.push({
    id: `executor-${roles.value.filter((r) => r.kind === 'executor').length + 1}`,
    name: '', kind: 'executor', executorId: '', modelId: '',
    skills: ['coding'], tools: [], permissions: {},
  })
}

async function save(role: SessionRole) {
  savingId.value = role.id
  msg.value = ''
  try {
    const saved = await apiPut<SessionRole>('/session-roles', role)
    Object.assign(role, saved)
    msg.value = t('config.sessionRoles.saved')
  } catch (e: any) {
    msg.value = e?.message || String(e)
  } finally {
    savingId.value = ''
    setTimeout(() => { msg.value = '' }, 4000)
  }
}

async function remove(role: SessionRole) {
  if (role.builtin || role.kind === 'architect' || role.id === 'architect') {
    msg.value = t('config.sessionRoles.architectProtected')
    setTimeout(() => { msg.value = '' }, 4000)
    return
  }
  msg.value = ''
  try {
    await apiDelete(`/session-roles/${role.id}`)
    roles.value = roles.value.filter((r) => r.id !== role.id)
  } catch (e: any) {
    msg.value = e?.message || String(e)
    setTimeout(() => { msg.value = '' }, 4000)
  }
}

/** 外部(远程)执行器: 生成并拷贝 skills/工具/权限注入指令(到远端 agent 粘贴执行)。 */
const copyHint = ref('')
async function copyInjection(role: SessionRole) {
  const ex = executors.value.find((x) => x.id === role.executorId)
  const lines = [
    `# 角色注入: ${role.name} (${role.id})`,
    ex ? `# 执行器: ${ex.id} (${ex.type} @ ${ex.host === 'remote' ? '远程' : '本机'})` : '',
    '## 允许的技能场景',
    ...(role.skills?.length ? role.skills.map((x) => `- ${x}`) : ['- (未限制)']),
    '## 工具白名单',
    ...(role.tools?.length ? role.tools.map((x) => `- ${x}`) : ['- (未限制)']),
    '## 权限配置',
    `- ${JSON.stringify(role.permissions ?? {})}`,
    '请以以上配置作为你的能力边界执行后续任务。',
  ].filter(Boolean)
  try {
    await navigator.clipboard.writeText(lines.join('\n'))
    copyHint.value = t('config.sessionRoles.copied')
  } catch {
    copyHint.value = lines.join('\n')
  }
  setTimeout(() => { copyHint.value = '' }, 6000)
}

function toggleSkill(role: SessionRole, skill: string) {
  role.skills = role.skills?.includes(skill)
    ? role.skills.filter((s) => s !== skill)
    : [...(role.skills ?? []), skill]
}
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="panel-header">
      <span class="flex items-center gap-2">
        <UserGroupIcon class="w-4 h-4 text-ctp-mauve" />{{ t('config.sessionRoles.title') }}
      </span>
      <span class="flex items-center gap-2">
        <button class="btn !py-1 !px-3 !text-xs" @click="addRole">
          <PlusIcon class="w-3.5 w-3.5" />{{ t('config.sessionRoles.add') }}
        </button>
      </span>
    </div>
    <div class="p-3 text-xs space-y-2">
      <div class="text-[11px] text-ctp-overlay0">{{ t('config.sessionRoles.desc') }}</div>
      <div v-if="msg" class="chip bg-ctp-blue/15 text-ctp-blue">{{ msg }}</div>

      <div
        v-for="r in roles"
        :key="r.id"
        class="border border-ctp-surface0 rounded-lg p-2.5 space-y-2"
        :class="{ 'border-ctp-mauve/30': r.builtin }"
      >
        <div class="flex items-center gap-2 flex-wrap">
          <span v-if="r.builtin" class="chip bg-ctp-mauve/15 text-ctp-mauve">{{ t('config.sessionRoles.builtin') }}</span>
          <input v-model="r.id" class="input !py-0.5 !text-xs font-mono w-36" :disabled="!!r.builtin" :title="t('config.sessionRoles.idHint')">
          <input v-model="r.name" class="input !py-0.5 !text-xs w-36" :placeholder="t('config.sessionRoles.namePh')">
          <template v-if="!r.builtin">
            <select v-model="r.executorId" class="input !py-0.5 !text-xs w-40">
              <option value="">{{ t('config.sessionRoles.pickExecutor') }}</option>
              <option v-for="e in executors" :key="e.id" :value="e.id">
                {{ e.id }}（{{ e.host === 'remote' ? t('config.executors.hostRemote') : t('config.executors.hostLocal') }}）
              </option>
            </select>
            <select v-model="r.modelId" class="input !py-0.5 !text-xs w-36" :disabled="!execModels(r).length">
              <option value="">{{ t('config.sessionRoles.pickModel') }}</option>
              <option v-for="m in execModels(r)" :key="m.id || m.name" :value="m.name">{{ m.name }}</option>
            </select>
          </template>
          <div class="flex-1" />
          <button class="btn btn-primary !py-0.5 !px-2.5 !text-[11px]" :disabled="savingId === r.id" @click="save(r)">
            {{ savingId === r.id ? t('config.sessionRoles.saving') : t('config.sessionRoles.save') }}
          </button>
          <button
            v-if="r.kind !== 'architect'"
            class="btn !py-0.5 !px-2 !text-[11px]"
            :title="t('config.sessionRoles.copyInjectHint')"
            @click="copyInjection(r)"
          >{{ t('config.sessionRoles.copyInject') }}</button>
          <button
            v-if="r.kind !== 'architect'"
            class="btn !py-0.5 !px-2 !text-[11px] text-ctp-red"
            @click="remove(r)"
          >
            <TrashIcon class="w-3 h-3" />
          </button>
        </div>

        <!-- 能力配置: 技能场景 + 工具白名单 -->
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-[10px] text-ctp-overlay1">{{ t('config.sessionRoles.skills') }}</span>
          <button
            v-for="sk in (r.skillPool ?? ['extract', 'plan', 'coding', 'capability', 'accept', 'naming', 'contract', 'linenote'])"
            :key="sk"
            class="chip !text-[10px] cursor-pointer"
            :class="r.skills?.includes(sk) ? 'bg-ctp-blue/20 text-ctp-blue' : 'bg-ctp-surface0/60 text-ctp-overlay1'"
            @click="toggleSkill(r, sk)"
          >
            {{ sk }}
          </button>
          <span class="ml-2 text-[10px] text-ctp-overlay1" :title="t('config.sessionRoles.toolsHint')">{{ t('config.sessionRoles.tools') }}</span>
          <input
            :value="(r.tools ?? []).join(', ')"
            class="input !py-0.5 !text-[11px] font-mono flex-1 min-w-48"
            :placeholder="t('config.sessionRoles.toolsPh')"
            @change="(ev: any) => { r.tools = String(ev.target.value || '').split(',').map((x: string) => x.trim()).filter(Boolean) }"
          >
        </div>
      </div>

      <div v-if="copyHint" class="text-[10px] font-mono text-ctp-overlay0 break-all whitespace-pre-wrap max-h-24 overflow-auto">{{ copyHint }}</div>
      <div v-if="!roles.length && !loading" class="text-ctp-overlay1">
        {{ t('config.sessionRoles.empty') }}
      </div>
    </div>
  </div>
</template>
