import { commonZh, commonEn } from '../i18n/common'
/**
 * 门户 i18n（基础服务）：用户中心所需词表。
 * 词表自 workbench i18n 迁入（auth / resource 全量 + settings/common/nav 所需键）。
 */
import { createAppI18n } from '../i18n/setup'
// auth 词表单一源（R3 修正：原此处 65 键内联拷贝，与 workbench 共享基线见 i18n/dicts/auth.ts）
import { authZh, authEn } from '../i18n/dicts/auth'

const zhCN = {
  nav: {
    home: '首页',
    backHome: '返回首页',
    userCenter: '用户中心',
    settings: '设置',
  },
  home: {
    sub: '源码架构分析 · 知识库管理 · AI 驱动的智能开发工作台',
    settings: '设置',
    userCenter: '用户中心',
    allSettings: '全部设置',
    footer: 'TopoCode · 统一 Web 工作台',
    modules: {
      kb: {
        title: '知识库解析和管理',
        desc: '项目导入 · 代码解析 · 任务分析 · 知识库管理，一站式管理你的代码知识资产。',
        chips: ['项目导入', '代码解析', '任务分析'],
      },
      projects: {
        title: '知识库文档浏览',
        desc: '浏览项目列表、任务文档与社区文档，快速定位知识库内容与文件摘要。',
        chips: ['项目列表', '任务文档', '社区文档'],
      },
      chat: {
        title: 'AI CHAT',
        desc: '与 AI 助手对话，查询代码、生成文档、执行分析，智能赋能研发全流程。',
        chips: ['智能问答', '文档生成', 'Agent 执行'],
      },
      architect: {
        title: 'Architect 工作台',
        desc: '需求驱动 · 架构驱动 Coding Agent：语义资产提取、需求分析与智能编码协作。',
        chips: ['语义资产', '需求驱动', 'Coding Agent'],
      },
    },
  },
  common: { ...commonZh },
  settings: {
    profile: '个人资料',
    resourceCenter: '资源中心',
    resourceCenterDesc: '浏览和下载可导入的结构分析包',
    noResources: '暂无资源',
    searchResource: '搜索资源',
    sortAsc: '正序',
    sortByDownloads: '下载量',
    sortByName: '名称',
    sortByTime: '时间',
    sortDesc: '倒序',
  },
  auth: { ...authZh },
  resource: {
    categoryAll: '全部',
    categoryPrerelease: '即将上线',
    categoryFree: '免费',
    categoryPoints: '积分兑换',
    center: '资源中心',
    centerDesc: '浏览和下载可导入的结构分析包',
    noResources: '暂无资源',
    loginHint: '登录后可下载资源',
    prerelease: '即将上线',
    owned: '已购',
    pricing: {
      free: '免费',
      points: '{cost} 积分',
      subscription: '会员',
      custom: '定制',
      pointsExchange: '{cost} 积分兑换',
      pointsInsufficient: '积分不足（需 {cost}）',
    },
    action: {
      download: '下载',
      reDownload: '重新下载',
    },
    comment: {
      title: '留言反馈',
      placeholder: '请输入您的反馈意见（仅管理员可见）',
      submitted: '留言已提交',
      submit: '提交',
      submitting: '提交中...',
    },
    offline: '已下架',
    notAvailable: '暂未开通',
    import: {
      gettingUrl: '正在获取下载地址...',
      downloading: '正在下载资源包...',
      importing: '正在导入项目...',
      importingResource: '正在导入资源...',
      completed: '导入完成',
      downloadFailed: '下载失败',
      downloadLimitReached: '下载次数已达上限',
      contactSupport: '联系客服申诉',
      importFailed: '导入失败',
    },
    error: {
      notFound: '资源不存在',
    },
    search: '搜索资源',
  },
}

const enUS = {
  nav: {
    home: 'Home',
    backHome: 'Back to Home',
    userCenter: 'User Center',
    settings: 'Settings',
  },
  home: {
    sub: 'Source code architecture analysis · Knowledge base management · AI-driven intelligent dev workbench',
    settings: 'Settings',
    userCenter: 'User Center',
    allSettings: 'All Settings',
    footer: 'TopoCode · Unified Web Workbench',
    modules: {
      kb: {
        title: 'Knowledge Base Parsing & Management',
        desc: 'Project import · Code parsing · Task analysis · Knowledge base management — manage your code knowledge assets in one place.',
        chips: ['Project Import', 'Code Parsing', 'Task Analysis'],
      },
      projects: {
        title: 'Knowledge Base Docs',
        desc: 'Browse project lists, task docs and community docs to locate knowledge base content and file summaries quickly.',
        chips: ['Project List', 'Task Docs', 'Community Docs'],
      },
      chat: {
        title: 'AI CHAT',
        desc: 'Chat with the AI assistant — query code, generate docs, run analyses. AI empowerment across the whole dev lifecycle.',
        chips: ['Q&A', 'Doc Generation', 'Agent Execution'],
      },
      architect: {
        title: 'Architect Workbench',
        desc: 'Requirement-driven & architecture-driven Coding Agent: semantic asset extraction, requirement analysis and intelligent coding collaboration.',
        chips: ['Semantic Assets', 'Requirement Driven', 'Coding Agent'],
      },
    },
  },
  common: { ...commonEn },
  settings: {
    profile: 'Profile',
    resourceCenter: 'Resource Center',
    resourceCenterDesc: 'Browse and download importable structure analysis packages',
    noResources: 'No resources available',
    searchResource: 'Search Resources',
    sortAsc: 'Ascending',
    sortByDownloads: 'Downloads',
    sortByName: 'Name',
    sortByTime: 'Time',
    sortDesc: 'Descending',
  },
  auth: { ...authEn },
  resource: {
    categoryAll: 'All',
    categoryPrerelease: 'Coming Soon',
    categoryFree: 'Free',
    categoryPoints: 'Points Exchange',
    center: 'Resource Center',
    centerDesc: 'Browse and download importable structure analysis packages',
    noResources: 'No resources available',
    loginHint: 'Log in to download resources',
    prerelease: 'Coming Soon',
    owned: 'Owned',
    pricing: {
      free: 'Free',
      points: '{cost} points',
      subscription: 'Subscription',
      custom: 'Custom',
      pointsExchange: 'Exchange {cost} points',
      pointsInsufficient: 'Insufficient points (need {cost})',
    },
    action: {
      download: 'Download',
      reDownload: 'Download Again',
    },
    comment: {
      title: 'Feedback',
      placeholder: 'Enter your feedback (visible to admins only)',
      submitted: 'Feedback submitted',
      submit: 'Submit',
      submitting: 'Submitting...',
    },
    offline: 'Offline',
    notAvailable: 'Not Available',
    import: {
      gettingUrl: 'Fetching download URL...',
      downloading: 'Downloading resource package...',
      importing: 'Importing project...',
      importingResource: 'Importing resource...',
      completed: 'Import complete',
      downloadFailed: 'Download failed',
      downloadLimitReached: 'Download limit reached',
      contactSupport: 'Contact support to appeal',
      importFailed: 'Import failed',
    },
    error: {
      notFound: 'Resource not found',
    },
    search: 'Search Resources',
  },
}

/** 门户 i18n 实例（共享键 topoone-locale） */
export function createPortalI18n() {
  return createAppI18n({
    'zh-CN': zhCN,
    'en-US': enUS,
  })
}
