<script setup lang="ts">
/**
 * W5 单测建议面板（2610-B1）——缺口建议清单 + 事实对账状态条。
 *
 * 基调（adoption-batch1 §1.4）：**建议视角，无强制步骤**——本面板只呈现
 * 供人参考的高风险无测试符号与对账状态，不构成工单；「发到会话」把建议
 * 指令送入当前打开的单测会话（无会话则禁用提示）。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, ChevronDownIcon, PaperAirplaneIcon } from '@heroicons/vue/24/outline'
import {
  unitTestAdviceService, unitTestService,
  type UnitTestAdvice, type UnitTestAdviceItem, type UnitTestFacts,
} from '@/services/unit-test-service'
import { useArchUnitTestStore } from '@/stores/unit-test-store'

const { t } = useI18n()
const store = useArchUnitTestStore()

const advice = ref<UnitTestAdvice | null>(null)
const facts = ref<UnitTestFacts | null>(null)
const loading = ref(false)
const errorText = ref('')
const expanded = ref<Record<string, boolean>>({})
const sending = ref<Record<string, boolean>>({})

const items = computed(() => advice.value?.items ?? [])
const emptyReason = computed(() => advice.value?.reason ?? '')
const hasSession = computed(() => !!store.activeSession)

async function refresh() {
  loading.value = true
  errorText.value = ''
  try {
    const [a, f] = await Promise.all([
      unitTestAdviceService.listAdvice(15),
      unitTestAdviceService.getFacts(),
    ])
    advice.value = a
    facts.value = f
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function toggle(item: UnitTestAdviceItem) {
  expanded.value[item.symbol] = !expanded.value[item.symbol]
}

async function sendToSession(item: UnitTestAdviceItem) {
  const session = store.activeSession
  if (!session || sending.value[item.symbol]) return
  sending.value[item.symbol] = true
  try {
    const stale = item.evidence?.baseline_stale
      ? `（注意：基线可能过期，${t('unitTest.advice.staleHint')}）` : ''
    await unitTestService.sendMessage(
      session,
      `${t('unitTest.advice.sendPrompt')}: ${item.symbol} (${item.file}:${item.line})`
      + `${stale ? ` ${stale}` : ''}\n${item.evidence?.neighborhood || ''}`,
    )
  } finally {
    sending.value[item.symbol] = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="h-full flex flex-col min-h-0 panel">
    <!-- 状态条: 对账 + 建议语义声明 -->
    <div class="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b border-ctp-surface0">
      <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ t('unitTest.advice.advisory') }}</span>
      <span v-if="facts" class="text-[11px] text-ctp-overlay1">
        {{ t('unitTest.advice.factsBar', { scanned: facts.scannedCount ?? 0, claimed: facts.claimedCount ?? 0 }) }}
      </span>
      <span v-if="facts?.claimedOnly?.length" class="text-[11px] text-ctp-peach">
        {{ t('unitTest.advice.claimedOnly', { n: facts.claimedOnly.length }) }}
      </span>
      <button class="ml-auto btn btn-sm" :disabled="loading" @click="refresh">
        <ArrowPathIcon class="w-3.5 h-3.5" :class="loading ? 'animate-spin' : ''" />
        {{ t('common.refresh') }}
      </button>
    </div>

    <div class="flex-1 min-h-0 overflow-auto p-4 space-y-2">
      <div v-if="errorText" class="text-xs text-ctp-red px-2">{{ errorText }}</div>

      <div v-else-if="emptyReason" class="px-2 py-8 text-center text-xs text-ctp-overlay0">
        {{ t(`unitTest.advice.reason.${emptyReason}`) }}
      </div>

      <div v-else-if="!items.length && !loading" class="px-2 py-8 text-center text-xs text-ctp-overlay0">
        {{ t('unitTest.advice.covered') }}
      </div>

      <div
        v-for="item in items"
        :key="item.symbol"
        class="rounded-lg border border-ctp-surface0 bg-ctp-mantle/60"
      >
        <div class="flex items-center gap-2 px-3 py-2">
          <span class="chip bg-ctp-mauve/15 text-ctp-mauve font-mono text-[10px]">{{ item.kind }}</span>
          <span class="font-mono text-xs text-ctp-text truncate">{{ item.symbol }}</span>
          <span class="text-[10px] text-ctp-overlay1 truncate">{{ item.file }}:{{ item.line }}</span>
          <span class="chip bg-ctp-yellow/10 text-ctp-yellow" :title="t('unitTest.advice.fanIn')">
            ⚖ {{ item.weight }} <span class="text-ctp-overlay1">(fan-in {{ item.fan_in }})</span>
          </span>
          <span v-if="item.evidence?.baseline_stale" class="chip bg-ctp-peach/15 text-ctp-peach text-[10px]">
            {{ t('unitTest.advice.stale') }}
          </span>
          <div class="ml-auto flex items-center gap-1">
            <button
              class="btn btn-sm"
              :disabled="!hasSession || sending[item.symbol]"
              :title="hasSession ? '' : t('unitTest.advice.needSession')"
              @click="sendToSession(item)"
            >
              <PaperAirplaneIcon class="w-3 h-3" />
              {{ t('unitTest.advice.send') }}
            </button>
            <button class="text-ctp-overlay1 hover:text-ctp-text" @click="toggle(item)">
              <ChevronDownIcon class="w-3.5 h-3.5 transition-transform" :class="expanded[item.symbol] ? 'rotate-180' : ''" />
            </button>
          </div>
        </div>
        <pre
          v-if="expanded[item.symbol] && item.evidence?.neighborhood"
          class="mx-3 mb-2 p-2 rounded bg-ctp-crust text-[10px] leading-relaxed text-ctp-subtext0 overflow-auto max-h-52 font-mono whitespace-pre"
        >{{ item.evidence.neighborhood }}</pre>
      </div>
    </div>
  </div>
</template>
