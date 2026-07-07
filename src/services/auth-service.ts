import type { UserProfile, TransactionRecord } from '@/types'
import { getDeviceId } from '@/utils/device-id'
import { mockUser, mockToken } from '@/utils/mock'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const USE_MOCK = (import.meta.env.DEV || !window.navigator.onLine) && !import.meta.env.VITE_DISABLE_MOCK

interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Device-Id': getDeviceId(),
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.message || `HTTP ${res.status}`)
  }
  const json: ApiResponse<T> = await res.json()
  if (!json.success) {
    throw new Error(json.message || '请求失败')
  }
  return json.data
}

function delay(ms = 400): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}

export const authService = {
  async login(email: string, password: string): Promise<{ token: string; user: any }> {
    if (USE_MOCK) {
      await delay()
      if (email === 'demo@example.com' && password === 'demo123') {
        const u = { ...mockUser, referral_code: 'ABC12345', points: 150 }
        return { token: mockToken, user: u }
      }
      throw new Error('邮箱或密码错误')
    }
    return request('/topoapi/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },

  async loginWithCode(params: { email?: string; phone?: string; code: string }): Promise<{ token: string; user: any }> {
    if (USE_MOCK) {
      await delay()
      if (params.email === 'demo@example.com' && params.code === '123456') {
        return { token: mockToken, user: { ...mockUser, points: 150 } }
      }
      throw new Error('验证码错误或已过期')
    }
    return request('/topoapi/auth/login-with-code', {
      method: 'POST',
      body: JSON.stringify(params),
    })
  },

  async register(username: string, email: string, password: string, emailCode: string, phone?: string, smsCode?: string, referralCode?: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    return request('/topoapi/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password, email_code: emailCode, phone, sms_code: smsCode, referral_code: referralCode }),
    })
  },

  async forgotPassword(email: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    return request('/topoapi/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    })
  },

  async resetPassword(email: string, code: string, newPassword: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    return request('/topoapi/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ email, code, new_password: newPassword }),
    })
  },

  async sendEmailCode(email: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    return request('/topoapi/auth/send-email-code', {
      method: 'POST',
      body: JSON.stringify({ email }),
    })
  },

  async sendSmsCode(phone: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    return request('/topoapi/auth/send-sms-code', {
      method: 'POST',
      body: JSON.stringify({ phone }),
    })
  },

  async fetchProfile(token: string): Promise<any> {
    if (USE_MOCK) {
      await delay()
      return { ...mockUser, referral_code: 'ABC12345', points: 150 }
    }
    return request('/topoapi/user/profile', {
      headers: { 'Authorization': `Bearer ${token}`, 'X-Device-Id': getDeviceId() },
    })
  },

  async getReferralInfo(token: string): Promise<{ referral_code: string; points_balance: number; share_link: string }> {
    if (USE_MOCK) {
      await delay()
      return { referral_code: 'ABC12345', points_balance: 150, share_link: 'https://topocode.cn/register?ref=ABC12345' }
    }
    return request('/topoapi/user/referral-info', {
      headers: { 'Authorization': `Bearer ${token}`, 'X-Device-Id': getDeviceId() },
    })
  },

  async getReferralStats(token: string): Promise<{ referred_count: number; active_count: number; total_points_awarded: number }> {
    if (USE_MOCK) {
      await delay()
      return { referred_count: 3, active_count: 2, total_points_awarded: 150 }
    }
    return request('/topoapi/user/referral-stats', {
      headers: { 'Authorization': `Bearer ${token}`, 'X-Device-Id': getDeviceId() },
    })
  },

  async getAccountInfo(token: string): Promise<{ balance: number; points: number }> {
    if (USE_MOCK) {
      await delay()
      return { balance: 120, points: 150 }
    }
    return request('/topoapi/user/account-info', {
      headers: { 'Authorization': `Bearer ${token}`, 'X-Device-Id': getDeviceId() },
    })
  },

  async getTransactions(token: string): Promise<TransactionRecord[]> {
    if (USE_MOCK) {
      await delay()
      return [
        { id: 1, type: 'recharge', currency: 'balance', amount: 100, balance_after: 100, description: '余额充值', created_at: '2026-06-28T10:30:00' },
        { id: 2, type: 'consume', currency: 'points', amount: -30, balance_after: 120, description: '兑换资源：Spring Boot 电商微服务架构分析', created_at: '2026-06-25T14:20:00' },
        { id: 3, type: 'consume', currency: 'balance', amount: -49, balance_after: 51, description: '购买资源：Unity 游戏客户端架构分析', created_at: '2026-06-22T09:15:00' },
        { id: 4, type: 'reward', currency: 'points', amount: 50, balance_after: 150, description: '邀请奖励：好友完成注册', created_at: '2026-06-20T16:00:00' },
        { id: 5, type: 'recharge', currency: 'balance', amount: 50, balance_after: 100, description: '余额充值', created_at: '2026-06-18T11:00:00' },
        { id: 6, type: 'consume', currency: 'points', amount: -20, balance_after: 100, description: '兑换资源：React 18 大型前端项目依赖分析', created_at: '2026-06-15T08:30:00' },
        { id: 7, type: 'reward', currency: 'points', amount: 100, balance_after: 120, description: '邀请奖励：好友首次登录', created_at: '2026-06-10T20:00:00' },
        { id: 8, type: 'consume', currency: 'points', amount: -15, balance_after: 20, description: '兑换资源：Vue 3 组件库架构分析', created_at: '2026-06-05T13:45:00' },
        { id: 9, type: 'reward', currency: 'points', amount: 35, balance_after: 35, description: '新手任务奖励', created_at: '2026-06-01T09:00:00' },
      ]
    }
    const resp = await request<{ total: number; page: number; page_size: number; items: TransactionRecord[] }>('/topoapi/user/transactions', {
      headers: { 'Authorization': `Bearer ${token}`, 'X-Device-Id': getDeviceId() },
    })
    return resp.items
  },

  async logout(token: string): Promise<void> {
    if (USE_MOCK) {
      await delay()
      return
    }
    await request('/topoapi/auth/logout', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'X-Device-Id': getDeviceId() },
    })
  },
}
