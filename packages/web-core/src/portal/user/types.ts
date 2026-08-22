/** 用户中心（基础服务）类型定义 —— 自 workbench 迁入 */

export interface UserProfile {
  id: number
  username: string
  email: string
  phone?: string
  avatar?: string
  referral_code?: string
  points?: number
  balance?: number
  has_password?: boolean
  created_at: string
}

/** 交易/订单记录 */
export interface TransactionRecord {
  id: number
  user_id?: number
  type: 'recharge' | 'consume' | 'reward'
  currency: 'balance' | 'points'
  amount: number
  balance_after: number
  description: string
  ref_type?: string
  ref_id?: number | null
  created_at: string
}

/** 免费资源 */
export interface Resource {
  id: number
  title: string
  description: string
  category: string
  thumbnail_url: string
  download_count: number
  is_free: boolean
  pricing_model: 'free' | 'points' | 'paid' | 'subscription' | 'custom'
  points_cost: number
  price_cny: number
  subscription_tier: string
  created_at: string
  status?: 'published' | 'prerelease' | 'offline'
  is_prerelease?: boolean
  oss_url?: string
  like_count?: number
  dislike_count?: number
  my_vote?: number
  theme?: ResourceTheme
}

/** 资源主题（服务端下发的展示提示） */
export interface ResourceTheme {
  color?: string | null
  badge_text?: string | null
  badge_style?: 'new' | 'hot' | 'sale' | 'promo' | null
  featured?: boolean
  icon_url?: string | null
  owned?: boolean
}

/** 资源分类定义（服务端下发） */
export interface ResourceCategory {
  key: string
  label: string
  color?: string | null
  scope?: string | null
  auth_required?: boolean
  icon?: string | null
  count?: number
}

/** 资源列表元信息（服务端下发） */
export interface ResourceListMeta {
  _version: string
  categories: ResourceCategory[]
  styles: Record<string, string>
  feature_flags: Record<string, boolean>
  labels: Record<string, string>
}
