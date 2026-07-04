<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth-store'

const { t } = useI18n()
const auth = useAuthStore()

const filterType = ref<'all' | 'recharge' | 'consume'>('all')

const filteredTransactions = computed(() => {
  if (filterType.value === 'all') return auth.transactions
  if (filterType.value === 'recharge')
    return auth.transactions.filter(t => t.type === 'recharge' || t.type === 'reward')
  return auth.transactions.filter(t => t.type === 'consume')
})

function formatDate(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function typeLabel(type: string): string {
  switch (type) {
    case 'recharge': return t('auth.orderRecharge', '充值')
    case 'consume': return t('auth.orderConsume', '消费')
    case 'reward': return t('auth.orderRecharge', '充值')
    default: return type
  }
}

function currencyLabel(curr: string): string {
  return curr === 'balance' ? t('auth.balance', '余额') : t('auth.points', '积分')
}

function amountStyle(amount: number) {
  return amount > 0 ? { color: 'var(--success)' } : { color: 'var(--error)' }
}

onMounted(async () => {
  if (auth.isAuthenticated) {
    await auth.fetchTransactions()
  }
})
</script>

<template>
  <div class="order-tab" v-if="auth.isAuthenticated">
    <h2 class="section-title">{{ t('auth.orderHistory', '交易记录') }}</h2>

    <div class="filter-bar">
      <button
        v-for="f in ([
          { id: 'all' as const, key: 'auth.orderAll' },
          { id: 'recharge' as const, key: 'auth.orderRecharge' },
          { id: 'consume' as const, key: 'auth.orderConsume' },
        ])"
        :key="f.id"
        class="filter-btn"
        :class="{ active: filterType === f.id }"
        @click="filterType = f.id"
      >{{ t(f.key) }}</button>
    </div>

    <div v-if="auth.loadingTransactions" class="loading">{{ t('common.loading') }}...</div>
    <div v-else-if="filteredTransactions.length === 0" class="empty">{{ t('settings.noResources', '暂无记录') }}</div>
    <table v-else class="order-table">
      <thead>
        <tr>
          <th>{{ t('auth.orderDate', '时间') }}</th>
          <th>{{ t('auth.orderType', '类型') }}</th>
          <th>{{ t('auth.orderCurrency', '币种') }}</th>
          <th>{{ t('auth.orderAmount', '金额') }}</th>
          <th>{{ t('auth.orderBalanceAfter', '余额') }}</th>
          <th>{{ t('auth.orderDescription', '说明') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="tx in filteredTransactions" :key="tx.id">
          <td class="cell-date">{{ formatDate(tx.created_at) }}</td>
          <td><span class="badge" :class="'badge-' + (tx.type === 'consume' ? 'red' : 'green')">{{ typeLabel(tx.type) }}</span></td>
          <td>{{ currencyLabel(tx.currency) }}</td>
          <td :style="amountStyle(tx.amount)">{{ tx.amount > 0 ? '+' : '' }}{{ tx.amount }}</td>
          <td>{{ tx.currency === 'balance' ? '¥' : '' }}{{ tx.balance_after }}</td>
          <td class="cell-desc">{{ tx.description }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-else class="not-logged-in">
    <p>{{ t('auth.loginHint', '登录后可查看交易记录') }}</p>
    <router-link to="/login" class="btn btn-primary btn-sm">{{ t('auth.login', '登录') }}</router-link>
  </div>
</template>

<style scoped>
.order-tab {
  max-width: 900px;
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text-primary);
}
.filter-bar {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}
.filter-btn {
  padding: 4px 12px;
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.filter-btn:hover {
  border-color: var(--accent);
  color: var(--text-primary);
}
.filter-btn.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.loading, .empty {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
  font-size: 12px;
}
.order-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.order-table th {
  text-align: left;
  padding: 8px 10px;
  font-weight: 500;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.order-table td {
  padding: 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text-primary);
}
.cell-date {
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
.cell-desc {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
}
.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 500;
}
.badge-green {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
}
.badge-red {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
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
