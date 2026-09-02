/**
 * auth 词表（R3 修正）：共享基线 + workbench 本地差异（专属键 + 措辞 override）。
 * 基线：@topo/web-core/i18n/dicts/auth（原 64+ 键内联拷贝已去重）。
 */
import { authZh } from '@topo/web-core/i18n/dicts/auth'

const overrides: Record<string, string> = {
  account: '邮箱 / 手机号',
  activeCount: '活跃人数',
  backHome: '← 返回首页',
  confirmPassword: '确认新密码',
  emailCode: '邮箱验证码',
  fileCountExceed: '项目 "{name}" 中 {language} 文件数量为 {count}，超过 {limit} 个文件限制，无法自动创建解析任务。请手动筛选语言类型和目录范围后再创建任务。',
  forgotPassword: '忘记密码',
  goToLogin: '去登录',
  hasAccount: '已有账号？去登录',
  hasAccountGoLogin: '已有账号？去登录',
  invalidCode: '验证码错误或已过期',
  invalidCredentials: '邮箱或密码错误',
  loginBtn: '登录',
  newPassword: '新密码（至少6位）',
  noAccount: '没有账号？立即注册',
  or: '或',
  passwordReset: '密码已重置',
  passwordSet: '密码已设置',
  phoneHint: '手机号（仅支持中国大陆）',
  referredCount: '邀请人数',
  registerBtn: '注册',
  registering: '注册中...',
  registrationFailed: '注册失败',
  requireAccount: '请填写邮箱或手机号',
  requireCode: '请填写验证码',
  requirePassword: '请填写密码',
  resend: '重新发送',
  rewardPoints: '奖励积分',
  sending: '发送中...',
  smsCode: '手机验证码',
  useCodeLogin: '验证码登录',
  useNewPasswordToLogin: '请使用新密码登录',
  usePasswordLogin: '密码登录',
  xiaohongshu: '小红书',
}

export default { auth: { ...authZh, ...overrides } }
