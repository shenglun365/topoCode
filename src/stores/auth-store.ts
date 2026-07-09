import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { UserProfile, TransactionRecord } from '@/types'
import { authService } from '@/services/auth-service'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserProfile | null>(null)
  const token = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const referralCode = ref('')
  const points = ref(0)
  const balance = ref(0)
  const totalRecharged = ref(0)
  const totalConsumed = ref(0)
  const totalPointsRewarded = ref(0)
  const transactions = ref<TransactionRecord[]>([])
  const loadingTransactions = ref(false)
  const transactionTotal = ref(0)
  const transactionPage = ref(1)
  const transactionPageSize = ref(20)
  const referralStats = ref({ total_referred: 0, total_earned: 0 })
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
        balance.value = user.value?.balance || 0
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
    balance.value = u.balance || 0
    localStorage.setItem('topocode_token', t)
    localStorage.setItem('topocode_user', JSON.stringify(u))
  }

  function clearSession() {
    token.value = null
    user.value = null
    referralCode.value = ''
    points.value = 0
    balance.value = 0
    totalRecharged.value = 0
    totalConsumed.value = 0
    totalPointsRewarded.value = 0
    transactions.value = []
    transactionTotal.value = 0
    transactionPage.value = 1
      referralStats.value = { total_referred: 0, total_earned: 0 }
    shareLink.value = ''
    localStorage.removeItem('topocode_token')
    localStorage.removeItem('topocode_user')
  }

  async function login(account: string, password: string): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      const result = await authService.login(account, password)
      saveSession(result.token, result.user)
      return true
    } catch (e: any) {
      error.value = e.message || '登录失败'
      return false
    } finally {
      loading.value = false
    }
  }

  async function loginWithCode(account: string, code: string): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      const result = await authService.loginWithCode(account, code)
      saveSession(result.token, result.user)
      return true
    } catch (e: any) {
      error.value = e.message || '验证码错误或已过期'
      return false
    } finally {
      loading.value = false
    }
  }

  async function register(username: string, email: string, password: string, emailCode: string, phone?: string, smsCode?: string, referralCode?: string): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      const result = await authService.register(username, email, password, emailCode, phone, smsCode, referralCode)
      saveSession(result.token, result.user)
      return true
    } catch (e: any) {
      error.value = e.message || '注册失败'
      return false
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      await authService.logout()
    } catch { /* ignore */ }
    clearSession()
  }

  async function fetchProfile() {
    if (!token.value) return
    try {
      const profile = await authService.fetchProfile()
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
      const info = await authService.getReferralInfo()
      referralCode.value = info.referral_code
      points.value = info.points_balance
      shareLink.value = info.random_share_link + `?ref=${info.referral_code}`
    } catch {}
  }

  async function loadReferralStats() {
    if (!token.value) return
    try {
      referralStats.value = await authService.getReferralStats()
    } catch {}
  }

  async function fetchAccountInfo() {
    if (!token.value) return
    try {
      const info = await authService.getAccountInfo()
      balance.value = info.balance
      points.value = info.points
      totalRecharged.value = info.total_recharged
      totalConsumed.value = info.total_consumed
      totalPointsRewarded.value = info.total_points_rewarded
    } catch {}
  }

  async function fetchTransactions(params?: { page?: number; type?: string; currency?: string }) {
    if (!token.value) return
    loadingTransactions.value = true
    try {
      const result = await authService.getTransactions({ ...params, page_size: transactionPageSize.value })
      transactions.value = result.items
      transactionTotal.value = result.total
      transactionPage.value = result.page
    } catch {} finally {
      loadingTransactions.value = false
    }
  }

  loadSession()

  return {
    user, token, loading, error, isAuthenticated,
    referralCode, points, balance, totalRecharged, totalConsumed, totalPointsRewarded, transactions, loadingTransactions, transactionTotal, transactionPage, transactionPageSize, referralStats, shareLink,
    login, loginWithCode, register, logout, fetchProfile,
    loadReferralInfo, loadReferralStats,
    fetchAccountInfo, fetchTransactions,
  }
})
