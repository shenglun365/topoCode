<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuth } from './use-auth'

const { t } = useI18n()
const auth = useAuth()
const refreshing = ref(false)

function fmtBalance(n: number): string {
  return t('auth.balanceAmount', { amount: n.toFixed(2) })
}
function fmtPoints(n: number): string {
  return t('auth.pointsAmount', { amount: String(n) })
}

async function refreshAccount() {
  refreshing.value = true
  try {
    await auth.fetchAccountInfo()
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  if (auth.isAuthenticated) {
    await auth.fetchAccountInfo()
  }
})
</script>

<template>
  <div
    v-if="auth.isAuthenticated"
    class="account-tab"
  >
    <div style="display:flex; align-items:center; gap:8px; margin-bottom:16px;">
      <h2
        class="section-title"
        style="margin-bottom:0;"
      >
        {{ t('auth.accountSummary', '账户概览') }}
      </h2>
      <button
        class="btn btn-ghost btn-icon btn-xs"
        :disabled="refreshing"
        :title="t('common.refresh')"
        @click="refreshAccount"
      >
        <svg
          class="icon-refresh"
          :class="{ spinning: refreshing }"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        ><path d="M21 2v6h-6" /><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M3 22v-6h6" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /></svg>
      </button>
    </div>

    <div class="cards">
      <div class="account-card balance-card">
        <div class="card-label">
          {{ t('auth.balance', '余额') }}
        </div>
        <div class="card-value">
          {{ fmtBalance(auth.balance) }}
        </div>
        <button
          class="card-btn"
          @click="$emit('recharge')"
        >
          {{ t('auth.recharge', '充值') }}
        </button>
      </div>
      <div class="account-card points-card">
        <div class="card-label">
          {{ t('auth.points', '积分') }}
        </div>
        <div class="card-value">
          {{ fmtPoints(auth.points) }}
        </div>
      </div>
    </div>

    <div class="summary">
      <div class="summary-item">
        <span class="summary-label">{{ t('auth.totalRecharged', '累计充值') }}</span>
        <span class="summary-value">¥{{ auth.totalRecharged.toFixed(2) }}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">{{ t('auth.totalConsumed', '累计消费') }}</span>
        <span class="summary-value">¥{{ auth.totalConsumed.toFixed(2) }}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">{{ t('auth.totalPointsRewarded', '累计获得积分') }}</span>
        <span class="summary-value">{{ auth.totalPointsRewarded }}</span>
      </div>
    </div>
  </div>
  <div
    v-else
    class="not-logged-in"
  >
    <p>{{ t('auth.loginHint', '登录后可查看账户信息') }}</p>
    <a
      href="/app/#/login"
      class="btn btn-primary btn-sm"
    >
      {{ t('auth.login', '登录') }}
    </a>
  </div>
</template>

<style scoped>
.account-tab {
  max-width: calc(600px * var(--ui-scale));
}
.section-title {
  font-size: calc(15px * var(--ui-scale));
  font-weight: 600;
  color: var(--text-primary);
}
.cards {
  display: flex;
  gap: calc(16px * var(--ui-scale));
  margin-bottom: calc(24px * var(--ui-scale));
}
.account-card {
  flex: 1;
  padding: calc(20px * var(--ui-scale));
  border-radius: 8px;
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.balance-card {
  background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
  border-color: #2d5a87;
}
.points-card {
  background: linear-gradient(135deg, #3b0764 0%, #6b21a8 100%);
  border-color: #6b21a8;
}
.card-label {
  font-size: calc(11px * var(--ui-scale));
  color: rgba(255,255,255,0.7);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.card-value {
  font-size: calc(24px * var(--ui-scale));
  font-weight: 700;
  color: #fff;
}
.card-btn {
  align-self: flex-start;
  margin-top: 4px;
  padding: 4px calc(14px * var(--ui-scale));
  font-size: calc(11px * var(--ui-scale));
  border: 1px solid rgba(255,255,255,0.3);
  border-radius: 4px;
  background: rgba(255,255,255,0.12);
  color: #fff;
  cursor: pointer;
  transition: background 0.15s;
}
.card-btn:hover {
  background: rgba(255,255,255,0.22);
}
.summary {
  display: flex;
  gap: calc(16px * var(--ui-scale));
}
.summary-item {
  flex: 1;
  padding: calc(12px * var(--ui-scale));
  background: var(--bg-secondary);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.summary-label {
  font-size: calc(11px * var(--ui-scale));
  color: var(--text-muted);
}
.summary-value {
  font-size: calc(14px * var(--ui-scale));
  font-weight: 600;
  color: var(--text-primary);
}
.not-logged-in {
  text-align: center;
  padding: calc(40px * var(--ui-scale));
  color: var(--text-muted);
  font-size: calc(13px * var(--ui-scale));
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: calc(12px * var(--ui-scale));
}
.icon-refresh { width: calc(16px * var(--ui-scale)); height: calc(16px * var(--ui-scale)); }
.icon-refresh.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
