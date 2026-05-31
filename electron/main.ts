/** Electron Main Process - 入口 + IPC 处理 (多窗口支持) */

import { app, ipcMain, dialog, shell, BrowserWindow } from 'electron'
import { join } from 'path'
import { existsSync, mkdirSync, writeFileSync } from 'fs'
import { windowManager } from './window-manager'
import { pythonBridge, HTTP_PORT } from './python-bridge'
import { zmqRouter } from './zmq-router'

// 开发环境设置
const isDev = !app.isPackaged

// Linux 沙箱配置 - 开发环境禁用 SUID 沙箱
if (process.platform === 'linux' && isDev) {
  app.disableHardwareAcceleration()
  app.commandLine.appendSwitch('no-sandbox')
}

// ==================== 日志系统 ====================

const LOG_DIR = join(app.getPath('userData'), 'logs')
const isDevEnv = !app.isPackaged

function ensureLogDir(): void {
  if (!existsSync(LOG_DIR)) {
    mkdirSync(LOG_DIR, { recursive: true })
  }
}

function getLogFilePath(): string {
  return LOG_FILE
}

// 应用启动时生成一次日志文件名，同一次启动所有日志写入同一文件
const launchTime = new Date()
const LOG_FILE = (() => {
  const dateStr = launchTime.toISOString().replace(/[:.]/g, '-').slice(0, 19)
  ensureLogDir()
  return join(LOG_DIR, `${dateStr}_electron.log`)
})()

function writeLog(level: string, source: string, message: string, data?: unknown): void {
  if (!isDevEnv) {
    // 生产环境只写错误日志，避免文件过大
    if (level !== 'ERROR') return
  }
  try {
    ensureLogDir()
    const now = new Date().toISOString()
    const dataStr = data ? ` | ${JSON.stringify(data)}` : ''
    const line = `[${now}] [${level}] [${source}] ${message}${dataStr}\n`
    writeFileSync(getLogFilePath(), line, { flag: 'a' })
  }
  catch (e) {
    // 日志写入失败不影响主流程
    console.error('[log] write failed:', e)
  }
}

// 包装 console 方法，自动写入日志文件
const originalConsole = { ...console }
console.log = (...args: any[]) => {
  originalConsole.log(...args)
  writeLog('INFO', 'electron', args.join(' '))
}
console.error = (...args: any[]) => {
  originalConsole.error(...args)
  writeLog('ERROR', 'electron', args.join(' '))
}
console.warn = (...args: any[]) => {
  originalConsole.warn(...args)
  writeLog('WARN', 'electron', args.join(' '))
}

// 渲染进程日志 IPC handler
ipcMain.on('log:debug', (_event, source: string, message: string, data?: unknown) => {
  writeLog('DEBUG', source, message, data)
})
ipcMain.on('log:info', (_event, source: string, message: string, data?: unknown) => {
  writeLog('INFO', source, message, data)
})
ipcMain.on('log:warn', (_event, source: string, message: string, data?: unknown) => {
  writeLog('WARN', source, message, data)
})
ipcMain.on('log:error', (_event, source: string, message: string, data?: unknown) => {
  writeLog('ERROR', source, message, data)
})

// ==================== IPC 处理 ====================

function setupIPC() {
  // ---- 窗口管理 (由 WindowManager 处理) ----
  windowManager.setupIPC()

  // ---- 文件选择 ----
  ipcMain.handle('dialog:open-directory', async () => {
    const win = windowManager.getFocusedWindow() || windowManager.getMainWindow()
    const result = await dialog.showOpenDialog(win!, {
      properties: ['openDirectory'],
    })
    return result.filePaths[0] || null
  })

  // ---- 文件读取 ----
  // Allowed directories for file access
  const allowedDirs: Set<string> = new Set()

  ipcMain.handle('fs:add-allowed-dir', async (_, dirPath: string) => {
    const path = await import('node:path')
    const resolved = path.resolve(dirPath)
    allowedDirs.add(resolved)
    return true
  })

  ipcMain.handle('fs:read-file', async (_, filePath: string) => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const resolved = path.resolve(filePath)
    // 安全检查：只允许读取已授权的项目目录
    const isAllowed = Array.from(allowedDirs).some(dir => resolved.startsWith(dir))
    if (!isAllowed) {
      throw new Error(`Access denied: ${resolved} is not in allowed directories`)
    }
    // 检查是否为目录
    const stat = fs.statSync(resolved)
    if (stat.isDirectory()) {
      throw new Error(`Cannot read directory: ${resolved}`)
    }
    return fs.readFileSync(resolved, 'utf-8')
  })

  // ---- 外部链接 ----
  ipcMain.handle('shell:open-external', async (_, url: string) => {
    console.log(`[open-external] ${url}`)
    await shell.openExternal(url)
  })

  // ---- 系统 ----
  ipcMain.handle('system:get-app-data-path', () => {
    return app.getPath('userData')
  })
  ipcMain.handle('system:get-http-port', () => {
    return HTTP_PORT
  })
  ipcMain.handle('env:get', (_, key: string) => {
    return process.env[key] || null
  })

  // ---- 存储 ----
  const store: Record<string, any> = {}

  ipcMain.handle('store:get', (_, key: string) => {
    return store[key]
  })

  ipcMain.handle('store:set', (_, key: string, value: any) => {
    store[key] = value
    return true
  })

  // ---- ZeroMQ RPC 调用 ----
  ipcMain.handle('ipc:call', async (_, { method, params }: { method: string; params: Record<string, any> }) => {
    console.log(`[Main] ipc:call -> ${method}`, params)
    try {
      const result = await zmqRouter.call(method, params)
      console.log(`[Main] ipc:call <- ${method} (success)`)
      // 强制深拷贝，过滤 Python 返回的不可克隆对象 (None→null, bytes→string)
      // Electron IPC 要求返回值必须是可结构化的 (structured clone)
      return JSON.parse(JSON.stringify(result))
    } catch (error: any) {
      console.error(`[Main] ipc:call error (${method}):`, error.message)
      throw new Error(`IPC call failed: ${error.message}`)
    }
  })
}

// ==================== 应用生命周期 ====================

app.whenReady().then(async () => {
  // 初始化 ZMQ Router
  await zmqRouter.connect()

  // ===== ZMQ PUB 事件 → Renderer 转发 =====
  // LLM 流式 chunk 事件需要广播到所有窗口
  zmqRouter.on('event', (event: { topic: string; eventType: string; data: any }) => {
    if (event.topic === 'llm') {
      const payload = {
        requestId: event.data?.requestId,
        eventType: event.eventType,  // chunk / tool_call / tool_result / done / error
        data: event.data,
      }
      windowManager.broadcast('zmq:event', payload)
    } else if (event.topic === 'project' || event.topic === 'task') {
      // 项目/任务事件（如 import.progress, syncing, task.progress 等）转发到渲染进程
      windowManager.broadcast(`event:${event.topic}.${event.eventType}`, event.data)
    }
  })

  // 设置 IPC
  setupIPC()

  // 创建第一个窗口
  windowManager.createWindow()

  // macOS: 点击 dock 重新打开窗口
  app.on('activate', () => {
    if (windowManager.getWindowCount() === 0) {
      windowManager.createWindow()
    }
  })
})

// 所有窗口关闭
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// 应用退出前清理 — 等待后端优雅停止
app.on('will-quit', (event) => {
  windowManager.cleanup()
  zmqRouter.close()

  // 延迟退出，等待后端进程停止
  event.preventDefault()
  pythonBridge.destroy().finally(() => {
    app.exit()
  })
})
