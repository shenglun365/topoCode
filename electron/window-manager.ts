/** 多窗口管理器 - 单后端共享 + 保活机制 */

import { BrowserWindow, app, ipcMain } from 'electron'
import { join } from 'path'
import { pythonBridge, BackendStatus } from './python-bridge'
import { zmqRouter } from './zmq-router'

// 最大窗口数
const MAX_WINDOWS = 1

// 后端保活超时（秒）- 最后一个窗口关闭后等待多久才停止后端
const BACKEND_KEEPALIVE_TIMEOUT = 60

export class WindowManager {
  private windows: Map<number, BrowserWindow> = new Map()
  private backendKeepaliveTimer: NodeJS.Timeout | null = null
  private isQuitting = false

  /** 获取所有窗口 */
  getWindows(): BrowserWindow[] {
    return Array.from(this.windows.values())
  }

  /** 获取窗口数量 */
  getWindowCount(): number {
    return this.windows.size
  }

  /** 获取主窗口（第一个创建的窗口） */
  getMainWindow(): BrowserWindow | null {
    const first = this.windows.keys().next().value
    return first ? this.windows.get(first) ?? null : null
  }

  /** 获取聚焦窗口 */
  getFocusedWindow(): BrowserWindow | null {
    return BrowserWindow.getFocusedWindow() && this.windows.has(BrowserWindow.getFocusedWindow()!.id)
      ? BrowserWindow.getFocusedWindow()!
      : null
  }

  /** 创建新窗口 */
  createWindow(options?: { show?: boolean }): BrowserWindow | null {
    // 检查窗口数量限制
    if (this.windows.size >= MAX_WINDOWS) {
      console.log('[WindowManager] Max windows reached')
      return null
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

    // 加载页面
    if (isDev) {
      win.loadURL('http://localhost:5173')
      if (options?.show) {
        win.webContents.openDevTools()
      }
    } else {
      win.loadFile(join(__dirname, '..', 'dist', 'index.html'))
    }

    // 配置中文字体
    this.configureFonts(win)

    // 注册窗口
    this.windows.set(win.id, win)
    console.log(`[WindowManager] Window ${win.id} created (${this.windows.size}/${MAX_WINDOWS})`)

    // 窗口关闭事件
    win.on('closed', () => {
      this.windows.delete(win.id)
      console.log(`[WindowManager] Window ${win.id} closed (${this.windows.size}/${MAX_WINDOWS})`)

      // 如果所有窗口都关闭了，启动保活定时器
      if (this.windows.size === 0 && !this.isQuitting) {
        this.startBackendKeepalive()
      }
    })

    // 窗口聚焦时广播
    win.on('focus', () => {
      this.broadcast('window:focus', { windowId: win.id })
    })

    // 启动后端（如果还没启动）
    this.ensureBackendRunning()

    return win
  }

  /** 确保后端运行 */
  private async ensureBackendRunning(): Promise<void> {
    const status = pythonBridge.getStatus()
    if (status.status !== 'running') {
      console.log('[WindowManager] Starting backend...')
      await pythonBridge.start()
    }
    // 清除保活定时器
    this.clearBackendKeepalive()
  }

  /** 后端健康检查（由定时器调用） */
  async healthCheck(): Promise<boolean> {
    try {
      const status = pythonBridge.getStatus()
      return status.status === 'running'
    } catch {
      return false
    }
  }

  /** 启动后端保活定时器 */
  private startBackendKeepalive(): void {
    this.clearBackendKeepalive()
    console.log(`[WindowManager] Backend keepalive: ${BACKEND_KEEPALIVE_TIMEOUT}s`)
    this.backendKeepaliveTimer = setTimeout(async () => {
      console.log('[WindowManager] Stopping backend (keepalive expired)')
      await pythonBridge.stop()
      this.backendKeepaliveTimer = null
    }, BACKEND_KEEPALIVE_TIMEOUT * 1000)
  }

  /** 清除保活定时器 */
  private clearBackendKeepalive(): void {
    if (this.backendKeepaliveTimer) {
      clearTimeout(this.backendKeepaliveTimer)
      this.backendKeepaliveTimer = null
    }
  }

  /** 向所有窗口广播消息 */
  broadcast(channel: string, data: any): void {
    for (const win of this.windows.values()) {
      if (!win.isDestroyed()) {
        win.webContents.send(channel, data)
      }
    }
  }

  /** 向指定窗口发送消息 */
  sendTo(windowId: number, channel: string, data: any): void {
    const win = this.windows.get(windowId)
    if (win && !win.isDestroyed()) {
      win.webContents.send(channel, data)
    }
  }

  /** 配置中文字体 */
  private configureFonts(win: BrowserWindow): void {
    win.webContents.insertCSS(`
      * {
        font-family: 'Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'Microsoft YaHei', 'PingFang SC', system-ui, sans-serif !important;
      }
      code, pre, .font-mono {
        font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Noto Sans Mono CJK SC', Consolas, monospace !important;
      }
    `)
  }

  /** 设置 IPC 处理 */
  setupIPC(): void {
    // ---- 窗口控制 ----
    ipcMain.handle('window:create', () => {
      return this.createWindow()?.id ?? null
    })

    ipcMain.handle('window:close', (event, windowId?: number) => {
      let win: BrowserWindow | null
      if (windowId) {
        win = this.windows.get(windowId) || null
      } else {
        win = BrowserWindow.fromWebContents(event.sender)
      }
      if (win && !win.isDestroyed()) {
        win.close()
      }
      return true
    })

    ipcMain.handle('window:minimize', (event) => {
      const win = BrowserWindow.fromWebContents(event.sender)
      if (win && !win.isDestroyed()) {
        win.minimize()
      }
      return true
    })

    ipcMain.handle('window:maximize', (event) => {
      const win = BrowserWindow.fromWebContents(event.sender)
      if (win && !win.isDestroyed()) {
        if (win.isMaximized()) {
          win.unmaximize()
        } else {
          win.maximize()
        }
      }
      return true
    })

    ipcMain.handle('window:isMaximized', (event) => {
      const win = BrowserWindow.fromWebContents(event.sender)
      return win && !win.isDestroyed() ? win.isMaximized() : false
    })

    ipcMain.handle('window:list', () => {
      return Array.from(this.windows.entries()).map(([id, win]) => ({
        id,
        title: win.getTitle(),
        isFocused: win.isFocused(),
      }))
    })

    ipcMain.handle('window:focus', (_, windowId: number) => {
      const win = this.windows.get(windowId)
      if (win && !win.isDestroyed()) {
        win.focus()
      }
      return true
    })

    ipcMain.handle('window:getCount', () => {
      return this.windows.size
    })

    ipcMain.handle('window:getMaxCount', () => {
      return MAX_WINDOWS
    })

    ipcMain.handle('window:toggle-left-panel', () => {
      const win = this.getFocusedWindow()
      win?.webContents.send('panel:toggle-left')
    })

    ipcMain.handle('window:toggle-right-panel', () => {
      const win = this.getFocusedWindow()
      win?.webContents.send('panel:toggle-right')
    })

    ipcMain.handle('window:zoom-in', () => {
      const win = this.getFocusedWindow()
      const zoom = win?.webContents.getZoomFactor() || 1
      win?.webContents.setZoomFactor(Math.min(3, zoom + 0.1))
      return Math.round((win?.webContents.getZoomFactor() || 1) * 100)
    })

    ipcMain.handle('window:zoom-out', () => {
      const win = this.getFocusedWindow()
      const zoom = win?.webContents.getZoomFactor() || 1
      win?.webContents.setZoomFactor(Math.max(0.33, zoom - 0.1))
      return Math.round((win?.webContents.getZoomFactor() || 1) * 100)
    })

    ipcMain.handle('window:zoom-reset', () => {
      this.getFocusedWindow()?.webContents.setZoomFactor(1)
      return 100
    })

    // ---- 广播消息 ----
    ipcMain.handle('window:broadcast', (_, channel: string, data: any) => {
      this.broadcast(channel, data)
      return true
    })

    // ---- 应用退出 ----
    ipcMain.handle('app:quit', () => {
      app.quit()
      return true
    })

    // ---- 后端管理 ----
    ipcMain.handle('backend:start', async () => {
      const status = await pythonBridge.start()
      this.broadcast('event:backend.status', status)
      return status
    })

    ipcMain.handle('backend:stop', async () => {
      const status = await pythonBridge.stop()
      this.broadcast('event:backend.status', status)
      return status
    })

    ipcMain.handle('backend:restart', async () => {
      const status = await pythonBridge.restart()
      this.broadcast('event:backend.status', status)
      return status
    })

    ipcMain.handle('backend:getStatus', () => {
      return pythonBridge.getStatus()
    })

    // 订阅后端状态变更
    pythonBridge.onStatusChange((status: BackendStatus) => {
      this.broadcast('event:backend.status', status)
    })

    // ---- 内存限制 ----
    ipcMain.handle('backend:getMemoryLimit', () => {
      return pythonBridge.memoryLimit
    })

    ipcMain.handle('backend:setMemoryLimit', (_, limit: number) => {
      pythonBridge.memoryLimit = limit
      return true
    })

    // ---- HTTP 服务配置 ----
    ipcMain.handle('backend:getHttpConfig', () => {
      return { host: pythonBridge.httpHost, port: pythonBridge.httpPort }
    })

    ipcMain.handle('backend:setHttpConfig', (_, config: { host: string; port: number }) => {
      pythonBridge.httpHost = config.host
      pythonBridge.httpPort = config.port
      return true
    })
  }

  /** 清理资源 */
  cleanup(): void {
    this.clearBackendKeepalive()
    this.isQuitting = true

    // 关闭所有窗口
    for (const win of this.windows.values()) {
      if (!win.isDestroyed()) {
        win.destroy()
      }
    }
    this.windows.clear()
  }
}

// 单例
export const windowManager = new WindowManager()
