<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth-store'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function handleLogin() {
  if (!email.value || !password.value) {
    errorMsg.value = '请填写邮箱和密码'
    return
  }
  loading.value = true
  errorMsg.value = ''
  const ok = await auth.login(email.value, password.value)
  loading.value = false
  if (ok) {
    router.push('/')
  } else {
    errorMsg.value = auth.error || '登录失败'
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-logo">◆</div>
      <h1 class="auth-title">{{ t('auth.login', 'TopoCode 登录') }}</h1>
      <form @submit.prevent="handleLogin">
        <div class="field">
          <input v-model="email" type="email" class="input" :placeholder="t('auth.email', '邮箱')" autocomplete="email">
        </div>
        <div class="field">
          <input v-model="password" type="password" class="input" :placeholder="t('auth.password', '密码')" autocomplete="current-password">
        </div>
        <div v-if="errorMsg" class="error">{{ errorMsg }}</div>
        <button type="submit" class="btn btn-primary btn-full" :disabled="loading">
          {{ loading ? t('common.loading', '登录中...') : t('auth.loginBtn', '登录') }}
        </button>
      </form>
      <div class="auth-links">
        <router-link to="/register">{{ t('auth.noAccount', '没有账号？立即注册') }}</router-link>
      </div>
      <div class="auth-back">
        <router-link to="/">{{ t('auth.backHome', '← 返回首页') }}</router-link>
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
.auth-links {
  margin-top: 16px;
  font-size: 12px;
}
.auth-links a {
  color: var(--accent);
  text-decoration: none;
}
.auth-back {
  margin-top: 12px;
  font-size: 12px;
}
.auth-back a {
  color: var(--text-muted);
  text-decoration: none;
}
</style>