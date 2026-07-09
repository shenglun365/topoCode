/** 单窗口管理器 - 单后端共享 + 保活机制 */

import { BrowserWindow, app, ipcMain, session } from 'electron'
import { join } from 'path'
import { pythonBridge, BackendStatus } from './python-bridge'

// 后端保活超时（秒）
const BACKEND_KEEPALIVE_TIMEOUT = 60

export class WindowManager {
  private mainWindow: BrowserWindow | null = null
  private backendKeepaliveTimer: NodeJS.Timeout | null = null
  private isQuitting = false

  getMainWindow(): BrowserWindow | null {
    return this.mainWindow
  }

  getFocusedWindow(): BrowserWindow | null {
    return this.mainWindow && !this.mainWindow.isDestroyed() ? this.mainWindow : null
  }

  /** 创建主窗口 */
  createWindow(options?: { show?: boolean }): BrowserWindow {
    if (this.mainWindow && !this.mainWindow.isDestroyed()) {
      this.mainWindow.focus()
      return this.mainWindow
    }

    const isDev = !app.isPackaged
    const win = new BrowserWindow({
      width: 1400,
      height: 900,
      minWidth: 1000,
      minHeight: 700,
      frame: false,
      backgroundColor: '#1e1e2e',
      show: options?.show ?? true,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: join(__dirname, 'preload.js'),
        spellcheck: false,
      },
    })

    if (isDev) {
      win.loadURL('http://localhost:5173')
      if (options?.show) win.webContents.openDevTools()
    } else {
      win.loadFile(join(__dirname, '..', 'dist', 'index.html'))
    }

    // 设置 Content-Security-Policy
    // unsafe-eval 必须放行：vue-i18n 依赖 new Function() 编译翻译模板
    const csp = isDev
      ? [
          "default-src 'self'",
          "script-src 'self' 'unsafe-eval'",
          "style-src 'self' 'unsafe-inline'",
          "img-src 'self' data: blob:",
          "connect-src 'self' ws://localhost:5173 http://localhost:* https://topocode.cn",
          "font-src 'self' data:",
          "object-src 'none'",
          "media-src 'self'",
        ].join('; ')
      : [
          "default-src 'self'",
          "script-src 'self' 'unsafe-eval'",
          "style-src 'self' 'unsafe-inline'",
          "img-src 'self' data: blob:",
          "connect-src 'self' https://topocode.cn",
          "font-src 'self' data:",
          "object-src 'none'",
          "media-src 'self'",
        ].join('; ')
    session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          'Content-Security-Policy': [csp],
        },
      })
    })

    this.configureFonts(win)

    this.mainWindow = win
    console.log(`[WindowManager] Main window created`)

    win.on('closed', () => {
      this.mainWindow = null
      if (!this.isQuitting) this.startBackendKeepalive()
    })

    win.on('maximize', () => {
      win.webContents.send('window:maximized-changed', true)
    })
    win.on('unmaximize', () => {
      win.webContents.send('window:maximized-changed', false)
    })

    this.ensureBackendRunning()
    return win
  }

  private async ensureBackendRunning(): Promise<void> {
    const status = pythonBridge.getStatus()
    if (status.status !== 'running' && status.status !== 'starting') {
      console.log('[WindowManager] Starting backend...')
      pythonBridge.start().then(s => {
        this.broadcastStatus(s)
      })
    }
    this.clearBackendKeepalive()
  }

  private startBackendKeepalive(): void {
    this.clearBackendKeepalive()
    console.log(`[WindowManager] Backend keepalive: ${BACKEND_KEEPALIVE_TIMEOUT}s`)
    this.backendKeepaliveTimer = setTimeout(async () => {
      console.log('[WindowManager] Stopping backend (keepalive expired)')
      const s = await pythonBridge.stop()
      this.broadcastStatus(s)
      this.backendKeepaliveTimer = null
    }, BACKEND_KEEPALIVE_TIMEOUT * 1000)
  }

  private clearBackendKeepalive(): void {
    if (this.backendKeepaliveTimer) {
      clearTimeout(this.backendKeepaliveTimer)
      this.backendKeepaliveTimer = null
    }
  }

  private broadcastStatus(status: BackendStatus): void {
    if (this.mainWindow && !this.mainWindow.isDestroyed()) {
      this.mainWindow.webContents.send('event:backend.status', status)
    }
  }

  /** 向主窗口广播事件 */
  broadcast(channel: string, data: any): void {
    if (this.mainWindow && !this.mainWindow.isDestroyed()) {
      this.mainWindow.webContents.send(channel, data)
    }
  }

  /** 向主窗口发送事件（broadcast 别名） */
  sendTo(_windowId: number, channel: string, data: any): void {
    this.broadcast(channel, data)
  }

  /** 获取窗口数量（始终返回 0 或 1） */
  getWindowCount(): number {
    return this.mainWindow && !this.mainWindow.isDestroyed() ? 1 : 0
  }

  private configureFonts(win: BrowserWindow): void {
    win.webContents.insertCSS(`
      * { font-family: 'Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'Microsoft YaHei', 'PingFang SC', system-ui, sans-serif !important; }
      code, pre, .font-mono { font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Noto Sans Mono CJK SC', Consolas, monospace !important; }
    `)
  }

  setupIPC(): void {
    ipcMain.handle('window:close', (event) => {
      const win = this.getWindowFromEvent(event)
      if (win) win.close()
      return true
    })

    ipcMain.handle('window:minimize', (event) => {
      this.getWindowFromEvent(event)?.minimize()
      return true
    })

    ipcMain.handle('window:maximize', (event) => {
      const win = this.getWindowFromEvent(event)
      if (win) {
        win.isMaximized() ? win.unmaximize() : win.maximize()
      }
      return true
    })

    ipcMain.handle('window:isMaximized', (event) => {
      return this.getWindowFromEvent(event)?.isMaximized() ?? false
    })

    ipcMain.handle('window:toggle-left-panel', () => {
      this.mainWindow?.webContents.send('panel:toggle-left')
    })

    ipcMain.handle('window:toggle-right-panel', () => {
      this.mainWindow?.webContents.send('panel:toggle-right')
    })

    ipcMain.handle('window:zoom-in', () => {
      const win = this.mainWindow
      const zoom = win?.webContents.getZoomFactor() || 1
      win?.webContents.setZoomFactor(Math.min(3, zoom + 0.1))
      return Math.round((win?.webContents.getZoomFactor() || 1) * 100)
    })

    ipcMain.handle('window:zoom-out', () => {
      const win = this.mainWindow
      const zoom = win?.webContents.getZoomFactor() || 1
      win?.webContents.setZoomFactor(Math.max(0.33, zoom - 0.1))
      return Math.round((win?.webContents.getZoomFactor() || 1) * 100)
    })

    ipcMain.handle('window:zoom-reset', () => {
      this.mainWindow?.webContents.setZoomFactor(1)
      return 100
    })

    ipcMain.handle('app:quit', () => {
      app.quit()
      return true
    })

    ipcMain.handle('backend:start', async () => {
      const s = await pythonBridge.start()
      this.broadcastStatus(s)
      return s
    })

    ipcMain.handle('backend:stop', async () => {
      const s = await pythonBridge.stop()
      this.broadcastStatus(s)
      return s
    })

    ipcMain.handle('backend:restart', async () => {
      const s = await pythonBridge.restart()
      this.broadcastStatus(s)
      return s
    })

    ipcMain.handle('backend:getStatus', () => {
      return pythonBridge.getStatus()
    })

    ipcMain.handle('backend:getMemoryLimit', () => pythonBridge.memoryLimit)
    ipcMain.handle('backend:setMemoryLimit', (_, limit: number) => {
      pythonBridge.memoryLimit = limit
      return true
    })

    ipcMain.handle('backend:getHttpConfig', () => {
      return { host: pythonBridge.httpHost, port: pythonBridge.httpPort }
    })
    ipcMain.handle('backend:setHttpConfig', (_, config: { host: string; port: number }) => {
      pythonBridge.httpHost = config.host
      pythonBridge.httpPort = config.port
      return true
    })

    pythonBridge.onStatusChange((status) => {
      this.broadcastStatus(status)
    })
  }

  private getWindowFromEvent(event: Electron.IpcMainInvokeEvent): BrowserWindow | null {
    const win = BrowserWindow.fromWebContents(event.sender)
    return win && !win.isDestroyed() ? win : this.mainWindow
  }

  cleanup(): void {
    this.clearBackendKeepalive()
    this.isQuitting = true
    if (this.mainWindow && !this.mainWindow.isDestroyed()) {
      this.mainWindow.destroy()
    }
    this.mainWindow = null
  }
}

export const windowManager = new WindowManager()
