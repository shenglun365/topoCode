<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth-store'
import { authService } from '@/services/auth-service'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const isSetPassword = route.query.set === '1' && auth.isAuthenticated && !auth.user?.has_password

const step = ref<'account' | 'reset' | 'done'>(isSetPassword ? 'reset' : 'account')
const account = ref('')
const code = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const errorMsg = ref('')

const codeSending = ref(false)
const codeSent = ref(false)
const codeCountdown = ref(0)
let countdownTimer: ReturnType<typeof setInterval> | null = null

function startCountdown() {
  codeCountdown.value = 60
  codeSent.value = true
  if (countdownTimer) clearInterval(countdownTimer)
  countdownTimer = setInterval(() => {
    codeCountdown.value--
    if (codeCountdown.value <= 0) {
      if (countdownTimer) clearInterval(countdownTimer)
      codeSent.value = false
    }
  }, 1000)
}

async function sendCode() {
  if (!account.value) { errorMsg.value = t('auth.validation.requireAccount'); return }
  codeSending.value = true
  errorMsg.value = ''
  try {
    await authService.sendCode(account.value)
    startCountdown()
    step.value = 'reset'
  } catch (e: any) {
    errorMsg.value = e.message || t('common.sendFailed')
  } finally {
    codeSending.value = false
  }
}

const canSubmit = computed(() => {
  if (!newPassword.value || newPassword.value.length < 6) return false
  if (newPassword.value !== confirmPassword.value) return false
  if (!isSetPassword && !code.value) return false
  return true
})

async function handleReset() {
  if (!canSubmit.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    if (isSetPassword) {
      await authService.setPassword(newPassword.value)
    } else {
      await authService.resetPassword(account.value, code.value, newPassword.value)
    }
    step.value = 'done'
  } catch (e: any) {
    errorMsg.value = e.message || t('common.operationFailed')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-logo">
        ◆
      </div>

      <template v-if="step === 'account'">
        <h1 class="auth-title">
          {{ t('auth.resetPassword') }}
        </h1>
        <form @submit.prevent="sendCode">
          <div class="field">
            <input
              v-model="account"
              class="input"
              :placeholder="t('auth.placeholder.account')"
              autocomplete="username"
            >
          </div>
          <div
            v-if="errorMsg"
            class="error"
          >
            {{ errorMsg }}
          </div>
          <button
            type="submit"
            class="btn btn-primary btn-full"
            :disabled="codeSending"
          >
            {{ codeSending ? t('auth.sending') : t('auth.sendCode') }}
          </button>
        </form>
      </template>

      <template v-if="step === 'reset'">
        <h1 class="auth-title">
          {{ isSetPassword ? t('auth.setPassword') : t('auth.resetPassword') }}
        </h1>
        <form @submit.prevent="handleReset">
          <div
            v-if="!isSetPassword"
            class="field"
          >
            <input
              :value="account"
              class="input"
              disabled
            >
          </div>
          <div
            v-if="!isSetPassword"
            class="field"
          >
            <div class="code-row">
              <input
                v-model="code"
                class="input flex-1"
                :placeholder="t('auth.placeholder.verificationCode')"
                maxlength="6"
              >
              <button
                type="button"
                class="btn btn-sm btn-ghost code-btn"
                :disabled="codeSending || codeSent"
                @click="sendCode"
              >
                {{ codeSending ? '...' : codeSent ? `${codeCountdown}s` : t('auth.resend') }}
              </button>
            </div>
          </div>
          <div class="field">
            <input
              v-model="newPassword"
              type="password"
              class="input"
              :placeholder="t('auth.placeholder.newPassword')"
              autocomplete="new-password"
            >
          </div>
          <div class="field">
            <input
              v-model="confirmPassword"
              type="password"
              class="input"
              :placeholder="t('auth.placeholder.confirmPassword')"
              autocomplete="new-password"
            >
          </div>
          <div
            v-if="errorMsg"
            class="error"
          >
            {{ errorMsg }}
          </div>
          <button
            type="submit"
            class="btn btn-primary btn-full"
            :disabled="loading || !canSubmit"
          >
            {{ loading ? t('common.processing') : (isSetPassword ? t('auth.setPassword') : t('auth.resetPassword')) }}
          </button>
        </form>
      </template>

      <template v-if="step === 'done'">
        <h1 class="auth-title">
          {{ isSetPassword ? t('auth.passwordSet') : t('auth.passwordReset') }}
        </h1>
        <p class="done-hint">
          {{ t('auth.useNewPasswordToLogin') }}
        </p>
        <button
          class="btn btn-primary btn-full"
          @click="router.push('/login')"
        >
          {{ t('auth.goToLogin') }}
        </button>
      </template>

      <div
        v-if="step !== 'done'"
        class="auth-back"
      >
        <router-link to="/login">
          {{ t('auth.backHome') }}
        </router-link>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
}
.auth-card {
  width: 360px;
  padding: 40px 32px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  text-align: center;
}
.auth-logo {
  font-size: 32px;
  color: var(--accent);
  margin-bottom: 8px;
}
.auth-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 24px;
}
.done-hint {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 16px;
}
.field {
  margin-bottom: 12px;
}
.input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
}
.input:focus {
  border-color: var(--accent);
}
.input:disabled {
  opacity: 0.5;
}
.flex-1 {
  flex: 1;
}
.code-row {
  display: flex;
  gap: 6px;
  align-items: center;
}
.code-btn {
  white-space: nowrap;
  flex-shrink: 0;
  font-size: 11px;
}
.error {
  color: var(--error);
  font-size: 12px;
  margin-bottom: 12px;
}
.btn-full {
  width: 100%;
  padding: 10px;
  font-size: 14px;
}
.auth-back {
  margin-top: 16px;
  font-size: 12px;
}
.auth-back a {
  color: var(--text-muted);
  text-decoration: none;
}
</style>
