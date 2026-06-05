/** Auto-updater — electron-updater with manual check trigger */

import { autoUpdater } from 'electron-updater'
import { BrowserWindow } from 'electron'

autoUpdater.autoDownload = false
autoUpdater.autoInstallOnAppQuit = true

// Feed URL — 通过环境变量覆盖，默认 GitHub Releases
const feedURL = process.env.UPDATE_FEED_URL || 'https://github.com/topocode/topoone-ui/releases/latest/download'
autoUpdater.setFeedURL(feedURL)

export type UpdateStatus = 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'

export interface UpdateInfo {
  status: UpdateStatus
  version?: string
  releaseNotes?: string
  error?: string
}

let statusListeners: Array<(info: UpdateInfo) => void> = []
let mainWindow: BrowserWindow | null = null

function notify(info: UpdateInfo) {
  for (const listener of statusListeners) {
    try { listener(info) } catch {}
  }
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('update:status', info)
  }
}

export function initUpdater(window: BrowserWindow) {
  mainWindow = window

  autoUpdater.on('checking-for-update', () => {
    console.log('[Updater] Checking for updates...')
    notify({ status: 'checking' })
  })

  autoUpdater.on('update-available', (info) => {
    console.log('[Updater] Update available:', info.version)
    notify({
      status: 'available',
      version: info.version,
      releaseNotes: typeof info.releaseNotes === 'string' ? info.releaseNotes : undefined,
    })
  })

  autoUpdater.on('update-not-available', () => {
    console.log('[Updater] No update available')
    notify({ status: 'not-available' })
  })

  autoUpdater.on('download-progress', () => {
    notify({ status: 'downloading' })
  })

  autoUpdater.on('update-downloaded', (info) => {
    console.log('[Updater] Update downloaded:', info.version)
    notify({
      status: 'downloaded',
      version: info.version,
    })
  })

  autoUpdater.on('error', (err) => {
    console.error('[Updater] Error:', err.message)
    notify({ status: 'error', error: err.message })
  })
}

export function checkForUpdates(force: boolean = false) {
  if (force) {
    autoUpdater.checkForUpdates()
  } else {
    autoUpdater.checkForUpdatesAndNotify()
  }
}

export function downloadUpdate() {
  autoUpdater.downloadUpdate()
}

export function quitAndInstall() {
  autoUpdater.quitAndInstall()
}

export function onUpdateStatus(cb: (info: UpdateInfo) => void) {
  statusListeners.push(cb)
  return () => {
    statusListeners = statusListeners.filter(l => l !== cb)
  }
}

export function getUpdateStatus(): UpdateInfo {
  return { status: 'checking' }
}
