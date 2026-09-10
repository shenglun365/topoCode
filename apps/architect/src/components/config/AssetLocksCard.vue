<script setup lang="ts">
/**
 * 并行执行资产锁（PR5）。
 *
 * 两级用户可调策略：strict 冲突硬阻断（任务 blocked）/ warn 警告放行（记录）。
 * 粒度：file 文件级（默认）/ component 组件级（语义资产 sa- 节点）。
 * 数据面：GET/PUT /exec/lock-policy（arch_collab_config）+ GET /exec/locks（当前持锁）。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { LockClosedIcon } from '@heroicons/vue/24/outline'
import { apiGet, apiPut } from '@/services/api-client'

interface LockRow { id: string; resource: string; granularity: string; holder: string; holderTitle?: string; acquiredAt?: number }
interface Policy { mode: 'strict' | 'warn'; granularity: 'file' | 'component' }

const { t } = useI18n()
const policy = ref<Policy>({ mode: 'strict', granularity: 'file' })
const locks = ref<LockRow[]>([])
const saving = ref(false)
const msg = ref('')

async function load() {
  try {
    const d = await apiGet<{ locks: LockRow[]; policy: Policy }>('/exec/locks')
    locks.value = d.locks ?? []
    policy.value = d.policy
  } catch { /* 列表失败保持旧值 */ }
}
onMounted(load)

async function save() {
  saving.value = true
  msg.value = ''
  try {
    policy.value = await apiPut<Policy>('/exec/lock-policy', policy.value)
    msg.value = t('config.locks.saved')
  } catch (e: any) {
    msg.value = e?.message || String(e)
  } finally {
    saving.value = false
    setTimeout(() => { msg.value = '' }, 4000)
  }
}

function fmtTime(ts?: number) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="panel-header">
      <span class="flex items-center gap-2">
        <LockClosedIcon class="w-4 h-4 text-ctp-red" />{{ t('config.locks.title') }}
      </span>
      <button class="btn btn-primary !py-1 !px-3 !text-xs" :disabled="saving" @click="save">
        {{ saving ? t('common.saving') : t('config.locks.save') }}
      </button>
    </div>
    <div class="p-3 text-xs space-y-2">
      <div class="text-[11px] text-ctp-overlay0">{{ t('config.locks.desc') }}</div>
      <div v-if="msg" class="chip bg-ctp-blue/15 text-ctp-blue">{{ msg }}</div>

      <div class="flex flex-wrap items-center gap-4">
        <div class="flex items-center gap-2">
          <span class="text-[10px] text-ctp-overlay1">{{ t('config.locks.mode') }}</span>
          <label class="flex items-center gap-1 text-[11px] cursor-pointer">
            <input v-model="policy.mode" value="strict" type="radio" name="lock-mode" class="accent-ctp-red">
            {{ t('config.locks.strict') }}
          </label>
          <label class="flex items-center gap-1 text-[11px] cursor-pointer">
            <input v-model="policy.mode" value="warn" type="radio" name="lock-mode" class="accent-ctp-yellow">
            {{ t('config.locks.warn') }}
          </label>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-[10px] text-ctp-overlay1">{{ t('config.locks.granularity') }}</span>
          <select v-model="policy.granularity" class="input !py-0.5 !text-xs w-28">
            <option value="file">{{ t('config.locks.file') }}</option>
            <option value="component">{{ t('config.locks.component') }}</option>
          </select>
        </div>
      </div>

      <!-- 当前持锁 -->
      <div class="border-t border-ctp-surface0/70 pt-2">
        <div class="text-[10px] text-ctp-overlay1 mb-1">{{ t('config.locks.current') }}</div>
        <div
          v-for="lk in locks"
          :key="lk.id"
          class="flex items-center gap-2 py-1 font-mono text-[11px]"
        >
          <span class="chip !text-[10px] bg-ctp-surface0/60 text-ctp-subtext1">{{ lk.granularity }}</span>
          <span class="min-w-0 flex-1 truncate text-ctp-text">{{ lk.resource }}</span>
          <span class="text-ctp-overlay0">{{ lk.holder }}</span>
          <span class="text-ctp-overlay0">{{ fmtTime(lk.acquiredAt) }}</span>
        </div>
        <p v-if="!locks.length" class="text-[11px] text-ctp-overlay1">{{ t('config.locks.empty') }}</p>
      </div>
    </div>
  </div>
</template>
