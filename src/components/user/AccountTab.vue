<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth-store'

const { t } = useI18n()
const auth = useAuthStore()

function fmtBalance(n: number): string {
  return t('auth.balanceAmount', { amount: n.toFixed(2) })
}
function fmtPoints(n: number): string {
  return t('auth.pointsAmount', { amount: String(n) })
}

onMounted(async () => {
  if (auth.isAuthenticated) {
    await auth.fetchAccountInfo()
  }
})
</script>

<template>
  <div class="account-tab" v-if="auth.isAuthenticated">
    <h2 class="section-title">{{ t('auth.accountSummary', '账户概览') }}</h2>

    <div class="cards">
      <div class="account-card balance-card">
        <div class="card-label">{{ t('auth.balance', '余额') }}</div>
        <div class="card-value">{{ fmtBalance(auth.balance) }}</div>
        <button class="card-btn" @click="$emit('recharge')">{{ t('auth.recharge', '充值') }}</button>
      </div>
      <div class="account-card points-card">
        <div class="card-label">{{ t('auth.points', '积分') }}</div>
        <div class="card-value">{{ fmtPoints(auth.points) }}</div>
      </div>
    </div>

    <div class="summary">
      <div class="summary-item">
        <span class="summary-label">{{ t('auth.totalRecharged', '累计充值') }}</span>
        <span class="summary-value">¥170.00</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">{{ t('auth.totalConsumed', '累计消费') }}</span>
        <span class="summary-value">¥49.00</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">{{ t('auth.totalPointsRewarded', '累计获得积分') }}</span>
        <span class="summary-value">185</span>
      </div>
    </div>
  </div>
  <div v-else class="not-logged-in">
    <p>{{ t('auth.loginHint', '登录后可查看账户信息') }}</p>
    <router-link to="/login" class="btn btn-primary btn-sm">{{ t('auth.login', '登录') }}</router-link>
  </div>
</template>

<style scoped>
.account-tab {
  max-width: 600px;
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text-primary);
}
.cards {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}
.account-card {
  flex: 1;
  padding: 20px;
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
  font-size: 11px;
  color: rgba(255,255,255,0.7);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.card-value {
  font-size: 24px;
  font-weight: 700;
  color: #fff;
}
.card-btn {
  align-self: flex-start;
  margin-top: 4px;
  padding: 4px 14px;
  font-size: 11px;
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
  gap: 16px;
}
.summary-item {
  flex: 1;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.summary-label {
  font-size: 11px;
  color: var(--text-muted);
}
.summary-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.not-logged-in {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
  font-size: 13px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
</style>
