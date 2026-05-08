/** Electron Main Process - 入口 + IPC 处理 (多窗口支持) */

import { app, ipcMain, dialog, shell, BrowserWindow } from 'electron'
import { join } from 'path'
import { windowManager } from './window-manager'
import { pythonBridge } from './python-bridge'
import { zmqRouter } from './zmq-router'

// 开发环境设置
const isDev = !app.isPackaged

// Linux 沙箱配置 - 开发环境禁用 SUID 沙箱
if (process.platform === 'linux' && isDev) {
  app.disableHardwareAcceleration()
  app.commandLine.appendSwitch('no-sandbox')
}

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
    await shell.openExternal(url)
  })

  // ---- 系统 ----
  ipcMain.handle('system:get-app-data-path', () => {
    return app.getPath('userData')
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
      return result
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
    // 清理资源
    zmqRouter.close()
    pythonBridge.destroy()
    app.quit()
  }
})

// 应用退出前清理
app.on('will-quit', () => {
  windowManager.cleanup()
  pythonBridge.destroy()
  zmqRouter.close()
})
