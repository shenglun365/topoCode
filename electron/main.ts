/** Electron Main Process - 入口 + IPC 处理 (多窗口支持) */

import { app, ipcMain, dialog, shell, BrowserWindow, net } from 'electron'
import { join } from 'path'
import { existsSync, mkdirSync, writeFileSync } from 'fs'
import { windowManager } from './window-manager'
import { pythonBridge, HTTP_PORT } from './python-bridge'
import { zmqRouter } from './zmq-router'
import { initUpdater, checkForUpdates, downloadUpdate, quitAndInstall } from './updater'

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

  ipcMain.handle('dialog:open-file', async (_, filters: { name: string; extensions: string[] }[]) => {
    const win = windowManager.getFocusedWindow() || windowManager.getMainWindow()
    const result = await dialog.showOpenDialog(win!, {
      properties: ['openFile'],
      filters: filters || [{ name: 'All Files', extensions: ['*'] }],
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
    // 安全检查：使用 path.relative 检测路径逃逸，防止 startsWith 绕过 (如 /allowedDir/../../etc)
    const isAllowed = Array.from(allowedDirs).some(dir => {
      const relative = path.relative(dir, resolved)
      return !relative.startsWith('..') && !path.isAbsolute(relative)
    })
    if (!isAllowed) {
      throw new Error(`Access denied: ${resolved} is not in allowed directories`)
    }
    // 检查是否为目录
    const stat = fs.statSync(resolved)
    if (stat.isDirectory()) {
      throw new Error(`Cannot read directory: ${resolved}`)
    }
    // 限制文件大小 (10MB)，防止大文件阻塞主线程
    if (stat.size > 10 * 1024 * 1024) {
      throw new Error(`File too large: ${resolved} (${stat.size} bytes > 10MB)`)
    }
    return fs.readFileSync(resolved, 'utf-8')
  })

  // ---- 外部链接 (仅允许 http/https) ----
  ipcMain.handle('shell:open-external', async (_, url: string) => {
    const parsed = new URL(url)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      throw new Error(`Blocked: only http/https URLs allowed, got ${parsed.protocol}`)
    }
    console.log(`[open-external] ${url}`)
    await shell.openExternal(url)
  })

  // ---- 在文件管理器中打开路径 ----
  ipcMain.handle('shell:open-path', async (_, dirPath: string) => {
    console.log(`[shell:open-path] ${dirPath}`)
    return shell.openPath(dirPath)
  })

  // ---- 从 URL 下载文件到临时目录 ----
  ipcMain.handle('file:download-url', async (_, url: string) => {
    console.log(`[file:download-url] downloading ${url.substring(0, 80)}...`)
    const path = await import('node:path')
    const os = await import('node:os')
    const fs = await import('node:fs')
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'topoone-dl-'))
    const ext = url.includes('.zip') ? '.zip' : '.tmp'
    const dest = path.join(tmpDir, `resource${ext}`)
    await new Promise<void>((resolve, reject) => {
      const req = net.request(url)
      req.on('response', (res) => {
        if (res.statusCode !== 200) {
          reject(new Error(`Download failed: HTTP ${res.statusCode}`))
          return
        }
        const chunks: Buffer[] = []
        res.on('data', (chunk: Buffer) => chunks.push(chunk))
        res.on('end', () => {
          fs.writeFileSync(dest, Buffer.concat(chunks))
          resolve()
        })
        res.on('error', reject)
      })
      req.on('error', reject)
      req.end()
    })
    console.log(`[file:download-url] saved to ${dest}`)
    return dest
  })

  // ---- 系统 ----
  ipcMain.handle('system:get-app-data-path', () => {
    return app.getPath('userData')
  })
  ipcMain.handle('system:get-http-port', () => {
    return HTTP_PORT
  })
  ipcMain.handle('env:get', (_, key: string) => {
    const ALLOWED = ['TOPCODE_UI_DEBUG', 'TOPOCODE_LOG_LEVEL', 'VITE_LOG_LEVEL']
    if (!ALLOWED.includes(key)) return null
    return process.env[key] || null
  })

  // ---- 设备指纹 ----
  const { machineId } = (() => {
    const crypto = require('node:crypto')
    const p = require('node:path')
    const fs = require('node:fs')
    const idFile = p.join(app.getPath('userData'), '.device-id')
    let id = ''
    try {
      id = fs.readFileSync(idFile, 'utf-8').trim()
    } catch {}
    if (!id || id.length < 16) {
      id = crypto.randomUUID()
      try { fs.writeFileSync(idFile, id, 'utf-8') } catch {}
    }
    return { machineId: id }
  })()
  ipcMain.handle('device:getId', () => machineId)

  // ---- 存储 ----
  const store: Record<string, any> = {}

  ipcMain.handle('store:get', (_, key: string) => {
    return store[key]
  })

  ipcMain.handle('store:set', (_, key: string, value: any) => {
    store[key] = value
    return true
  })

  // ---- 资源项目目录配置 ----
  ipcMain.handle('backend:set-resource-dir', async (_, dirPath: string) => {
    return zmqRouter.call('backend.setResourceDir', { dirPath })
  })

  // ---- ZeroMQ RPC 调用 ----
  ipcMain.handle('ipc:call', async (_, { method, params }: { method: string; params: Record<string, any> }) => {
    const noisy = [
      'analysis.getAgentProgress',
      'analysis.getPreSummaryStatus',
      'analysis.getAgentTaskHistory',
      'backend.ping',
      'graph.loadPositions',
      'report.listSubDocs',
      'report.getSubDoc',
    ]
    const logParams = method === 'graph.savePositions' && params?.positions
      ? { ...params, positions: `${params.positions.length} entries` }
      : params
    if (!noisy.includes(method)) console.log(`[Main] ipc:call -> ${method}`, logParams)
    try {
      const result = await zmqRouter.call(method, params)
      if (!noisy.includes(method)) console.log(`[Main] ipc:call <- ${method} (success)`)
      return JSON.parse(JSON.stringify(result))
    } catch (error: any) {
      console.error(`[Main] ipc:call error (${method}):`, error.message)
      throw new Error(`IPC call failed: ${error.message}`)
    }
  })

  // ---- Auto-update ----
  ipcMain.handle('update:check', () => {
    checkForUpdates(true)
    return true
  })
  ipcMain.handle('update:download', () => {
    downloadUpdate()
    return true
  })
  ipcMain.handle('update:install', () => {
    quitAndInstall()
    return true
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

  // 初始化 auto-updater
  const win = windowManager.getMainWindow()
  if (win) {
    initUpdater(win)
  }

  // 定期健康检查（每 30s 探测一次 ZMQ 连通性）
  // 有正在处理中的请求时跳过检查，避免 ping 超时导致重连中断长操作
  setInterval(async () => {
    if (zmqRouter.pendingCount > 0) return
    const healthy = await zmqRouter.ping()
    if (!healthy) {
      console.warn('[Main] Backend health check failed, attempting reconnect...')
      try {
        await zmqRouter.close()
        await zmqRouter.connect()
      } catch (e: any) {
        console.error('[Main] Reconnect failed:', (e as Error).message)
      }
    }
  }, 30000)

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
