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
import knowledge from './knowledge'
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
  ...knowledge,
  ...nav,
  ...onboarding,
  ...pageTitle,
  ...preview,
  ...project,
  ...resource,
  ...render,
  ...report,
  ...settings,
  ...shell,
  ...theme,
  ...version,
  ...visualization,
  ..._window,
}
