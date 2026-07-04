import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { UserProfile } from '@/types'
import { authService } from '@/services/auth-service'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserProfile | null>(null)
  const token = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const referralCode = ref('')
  const points = ref(0)
  const referralStats = ref({ referred_count: 0, active_count: 0, total_points_awarded: 0 })
  const shareLink = ref('')

  const isAuthenticated = computed(() => !!token.value && !!user.value)

  function loadSession() {
    const savedToken = localStorage.getItem('topocode_token')
    const savedUser = localStorage.getItem('topocode_user')
    if (savedToken && savedUser) {
      token.value = savedToken
      try {
        user.value = JSON.parse(savedUser)
        referralCode.value = user.value?.referral_code || ''
        points.value = user.value?.points || 0
      } catch {
        clearSession()
      }
    }
  }

  function saveSession(t: string, u: any) {
    token.value = t
    user.value = u
    referralCode.value = u.referral_code || ''
    points.value = u.points || 0
    localStorage.setItem('topocode_token', t)
    localStorage.setItem('topocode_user', JSON.stringify(u))
  }

  function clearSession() {
    token.value = null
    user.value = null
    referralCode.value = ''
    points.value = 0
    referralStats.value = { referred_count: 0, active_count: 0, total_points_awarded: 0 }
    shareLink.value = ''
    localStorage.removeItem('topocode_token')
    localStorage.removeItem('topocode_user')
  }

  async function login(email: string, password: string): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      const result = await authService.login(email, password)
      saveSession(result.token, result.user)
      return true
    } catch (e: any) {
      error.value = e.message || '登录失败'
      return false
    } finally {
      loading.value = false
    }
  }

  async function register(username: string, email: string, password: string, emailCode: string, phone?: string, smsCode?: string, referralCode?: string): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      await authService.register(username, email, password, emailCode, phone, smsCode, referralCode)
      return true
    } catch (e: any) {
      error.value = e.message || '注册失败'
      return false
    } finally {
      loading.value = false
    }
  }

  function logout() {
    clearSession()
  }

  async function fetchProfile() {
    if (!token.value) return
    try {
      const profile = await authService.fetchProfile(token.value)
      user.value = profile
      referralCode.value = profile.referral_code || ''
      points.value = profile.points || 0
      localStorage.setItem('topocode_user', JSON.stringify(profile))
    } catch {
      clearSession()
    }
  }

  async function loadReferralInfo() {
    if (!token.value) return
    try {
      const info = await authService.getReferralInfo(token.value)
      referralCode.value = info.referral_code
      points.value = info.points_balance
      shareLink.value = info.share_link
    } catch {}
  }

  async function loadReferralStats() {
    if (!token.value) return
    try {
      referralStats.value = await authService.getReferralStats(token.value)
    } catch {}
  }

  loadSession()

  return {
    user, token, loading, error, isAuthenticated,
    referralCode, points, referralStats, shareLink,
    login, register, logout, fetchProfile,
    loadReferralInfo, loadReferralStats,
  }
})