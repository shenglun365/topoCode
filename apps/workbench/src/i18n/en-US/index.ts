import { portalEn } from '@topo/web-core/portal/i18n'
import chatAppEn from '../chat-app-en-US'
import ai from './ai'
import analysis from './analysis'
import auth from './auth'
import animation from './animation'
import chat from './chat'
import code from './code'
import common from './common'
import datetime from './datetime'
import diagram from './diagram'
import file from './file'
import group from './group'
import guide from './guide'
import _import from './import'
import nav from './nav'
import onboarding from './onboarding'
import pageTitle from './pageTitle'
import preview from './preview'
import project from './project'
import resource from './resource'
import render from './render'
import report from './report'
import settings from './settings'
import shell from './shell'
import theme from './theme'
import version from './version'
import visualization from './visualization'
import _window from './window'

const base = {
  ...portalEn,
  ...common,
  ...ai,
  ...analysis,
  ...auth,
  ...animation,
  ...chat,
  ...code,
  ...datetime,
  ...diagram,
  ...file,
  ...group,
  ...guide,
  ..._import,
  ...nav,
  ...onboarding,
  ...pageTitle,
  ...preview,
  ...project,
  ...resource,
  ...render,
  ...report,
  // portal 嵌套 settings 词表(设置中心页)与 workbench 扁平 settings 词表合并：
  // portal 侧在后保证 tabs/models/general 等嵌套键完整；workbench 侧独有键(title/skills/plugins 等)保留
  settings: { ...settings.settings, ...portalEn.settings },
  ...shell,
  ...theme,
  ...version,
  ...visualization,
  ..._window,
}

// MS7-W3: chat 子应用文案并入(顶层命名空间深合并——已有键 workbench 优先, chat 补缺)
function mergeChatApp<T extends Record<string, any>>(base: T, extra: Record<string, any>): T {
  const out: any = { ...base }
  for (const k of Object.keys(extra)) {
    out[k] = out[k] && typeof out[k] === 'object' ? { ...extra[k], ...out[k] } : (out[k] ?? extra[k])
  }
  return out
}

export default mergeChatApp(base, chatAppEn)
