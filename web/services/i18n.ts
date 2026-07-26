const locale = navigator.language.startsWith('zh') ? 'zh-CN' : 'en-US'

const messages: Record<string, Record<string, string>> = {
  'zh-CN': {
    'loading': '加载中...',
    'search': '搜索',
    'cancel': '取消',
    'confirm': '确认',
    'delete': '删除',
    'save': '保存',
    'close': '关闭',
    'noData': '暂无数据',
    'back': '返回',
    'networkErr': '网络错误',
    'pageNotFound': '页面未找到',
  },
  'en-US': {
    'loading': 'Loading...',
    'search': 'Search',
    'cancel': 'Cancel',
    'confirm': 'Confirm',
    'delete': 'Delete',
    'save': 'Save',
    'close': 'Close',
    'noData': 'No data',
    'back': 'Back',
    'networkErr': 'Network error',
    'pageNotFound': 'Page not found',
  },
}

export function t(key: string, fallback?: string): string {
  return messages[locale]?.[key] || messages['zh-CN'][key] || fallback || key
}

export function getLocale(): string {
  return locale
}
