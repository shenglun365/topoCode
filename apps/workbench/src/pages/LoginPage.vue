<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth-store'
import { authService } from '@/services/auth-service'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const loginMode = ref<'password' | 'code'>('password')
const account = ref('')
const password = ref('')
const code = ref('')
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
  if (codeSending.value || codeSent.value) return
  if (!account.value) { errorMsg.value = t('auth.validation.requireAccount'); return }
  codeSending.value = true
  errorMsg.value = ''
  try {
    await authService.sendCode(account.value)
    startCountdown()
  } catch (e: any) {
    errorMsg.value = e.message || t('common.sendFailed')
  } finally {
    codeSending.value = false
  }
}

function toggleMode() {
  loginMode.value = loginMode.value === 'password' ? 'code' : 'password'
  errorMsg.value = ''
  code.value = ''
  codeSent.value = false
  if (countdownTimer) clearInterval(countdownTimer)
}

async function handleLogin() {
  errorMsg.value = ''

      if (!account.value) { errorMsg.value = t('auth.validation.requireAccount'); return }

  if (loginMode.value === 'password') {
      if (!password.value) { errorMsg.value = t('auth.validation.requirePassword'); return }
    loading.value = true
    const ok = await auth.login(account.value, password.value)
    loading.value = false
    if (ok) {
      router.push('/')
    } else {
      errorMsg.value = auth.error || t('auth.error.invalidCredentials')
    }
  } else {
      if (!code.value) { errorMsg.value = t('auth.validation.requireCode'); return }
    loading.value = true
    const ok = await auth.loginWithCode(account.value, code.value)
    loading.value = false
    if (ok) {
      router.push('/')
    } else {
      errorMsg.value = auth.error || t('auth.error.invalidCode')
    }
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-logo">
        ◆
      </div>
      <h1 class="auth-title">
        {{ t('auth.login') }}
      </h1>
      <form @submit.prevent="handleLogin">
        <div class="field">
          <input
            v-model="account"
            class="input"
            :placeholder="t('auth.placeholder.account')"
            autocomplete="username"
          >
        </div>
        <div
          v-if="loginMode === 'password'"
          class="field"
        >
          <input
            v-model="password"
            type="password"
            class="input"
            :placeholder="t('auth.password')"
            autocomplete="current-password"
          >
        </div>
        <div
          v-if="loginMode === 'code'"
          class="field"
        >
          <div class="code-row">
            <input
              v-model="code"
              class="input flex-1"
              :placeholder="t('auth.placeholder.verificationCode')"
              maxlength="6"
              autocomplete="one-time-code"
            >
            <button
              type="button"
              class="btn btn-sm btn-ghost code-btn"
              :disabled="codeSending || codeSent"
              @click="sendCode"
            >
              {{ codeSending ? '...' : codeSent ? `${codeCountdown}s` : t('auth.sendCode') }}
            </button>
          </div>
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
          :disabled="loading"
        >
          {{ loading ? t('common.loading') : t('auth.loginBtn') }}
        </button>
      </form>
      <div
        class="toggle-mode"
        @click="toggleMode"
      >
        {{ loginMode === 'password' ? t('auth.useCodeLogin') : t('auth.usePasswordLogin') }}
      </div>
      <div class="auth-links">
        <router-link to="/register">
          {{ t('auth.noAccount') }}
        </router-link>
        <span class="sep">|</span>
        <router-link
          to="/reset-password"
          class="link-muted"
        >
          {{ t('auth.forgotPassword') }}
        </router-link>
      </div>
      <div class="auth-back">
        <router-link to="/">
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
  width: calc(400px * var(--ui-scale, 1));
  padding: calc(40px * var(--ui-scale, 1)) calc(32px * var(--ui-scale, 1));
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: calc(12px * var(--ui-scale, 1));
  text-align: center;
}
.auth-logo {
  font-size: calc(32px * var(--ui-scale, 1));
  color: var(--accent);
  margin-bottom: calc(8px * var(--ui-scale, 1));
}
.auth-title {
  font-size: calc(18px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: calc(24px * var(--ui-scale, 1));
}
.field {
  margin-bottom: calc(10px * var(--ui-scale, 1));
}
.input {
  width: 100%;
  padding: calc(10px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: calc(13px * var(--ui-scale, 1));
  outline: none;
  box-sizing: border-box;
}
.input:focus {
  border-color: var(--accent);
}
.flex-1 {
  flex: 1;
}
.code-row {
  display: flex;
  gap: calc(6px * var(--ui-scale, 1));
  align-items: center;
}
.code-btn {
  white-space: nowrap;
  flex-shrink: 0;
  font-size: calc(11px * var(--ui-scale, 1));
}
.error {
  color: var(--error);
  font-size: calc(12px * var(--ui-scale, 1));
  margin-bottom: calc(12px * var(--ui-scale, 1));
}
.btn-full {
  width: 100%;
  padding: calc(10px * var(--ui-scale, 1));
  font-size: calc(14px * var(--ui-scale, 1));
}
.toggle-mode {
  margin-top: calc(10px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--accent);
  cursor: pointer;
  opacity: 0.8;
}
.toggle-mode:hover {
  opacity: 1;
  text-decoration: underline;
}
.auth-links {
  margin-top: calc(14px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
}
.auth-links a {
  color: var(--accent);
  text-decoration: none;
}
.auth-links .sep {
  color: var(--border);
  margin: 0 calc(6px * var(--ui-scale, 1));
}
.auth-links .link-muted {
  color: var(--text-muted);
}
.auth-back {
  margin-top: calc(12px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
}
.auth-back a {
  color: var(--text-muted);
  text-decoration: none;
}
</style>
