import { portalZh } from '@topo/web-core/portal/i18n'
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

export default {
  ...portalZh,
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
  settings: { ...settings.settings, ...portalZh.settings },
  ...shell,
  ...theme,
  ...version,
  ...visualization,
  ..._window,
}
